from sqlalchemy.orm import Session

from sqlalchemy import case, desc, func, literal, literal_column, or_, text

from app.models.order_item import OrderItem
from app.models.product import Product
from app.core.config import settings

from app.schemas.product import (
    ProductCreate,
    ProductUpdate
)

from app.crud.product import (
    create_product,
    get_product_by_id,
    delete_product
)

from app.utils.pagination import paginate


class ProductHasOrderHistoryError(Exception):
    """Raised when deleting a product would break historical order references."""



def create_new_product(
    db: Session,
    product_data: ProductCreate,
    owner_id: int
):

    product = Product(

        name=product_data.name,

        description=product_data.description,

        price=product_data.price,

        stock=product_data.stock,

        image_url=product_data.image_url,

        owner_id=owner_id

    )


    return create_product(
        db,
        product
    )



def get_all_products(
    db: Session,
    page: int = 1,
    limit: int = 10,
    search: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    stock_available: bool | None = None,
    search_mode: str = "hybrid",
):

    query = db.query(Product)



    # Search by product name or description

    if search and search.strip():
        search_text = search.strip()
        search_terms = list(dict.fromkeys(search_text.split()))

        def contains_pattern(term: str) -> str:
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            return f"%{escaped}%"

        if db.bind is not None and db.bind.dialect.name == "postgresql":
            vector = func.to_tsvector(
                literal_column("'english'"),
                func.coalesce(Product.name, literal_column("''"))
                + literal_column("' '")
                + func.coalesce(Product.description, literal_column("''")),
            )
            terms = func.plainto_tsquery("english", search_text)
            full_text_match = vector.op("@@")(terms)
            fuzzy_terms = list(dict.fromkeys(
                term for term in [search_text, *search_terms] if len(term) >= 3
            ))
            if fuzzy_terms:
                db.execute(
                    text("SELECT set_config('pg_trgm.word_similarity_threshold', :threshold, true)"),
                    {"threshold": str(settings.PRODUCT_SEARCH_SIMILARITY_THRESHOLD)},
                )
                fuzzy_match = or_(*(
                    condition
                    for term in fuzzy_terms
                    for condition in (
                        literal(term).bool_op("<%")(Product.name),
                        literal(term).bool_op("<%")(Product.description),
                    )
                ))
                fuzzy_score = func.greatest(*(
                    func.word_similarity(term, column)
                    for term in fuzzy_terms
                    for column in (Product.name, Product.description)
                ))
            else:
                fuzzy_match = literal_column("false")
                fuzzy_score = literal_column("0.0")
            partial_match = or_(*(
                condition
                for term in search_terms
                for condition in (
                    Product.name.ilike(contains_pattern(term), escape="\\"),
                    Product.description.ilike(contains_pattern(term), escape="\\"),
                )
            ))
            if search_mode == "full_text":
                query = query.filter(full_text_match)
                query = query.order_by(desc(func.ts_rank_cd(vector, terms)))
            elif search_mode == "fuzzy":
                query = query.filter(or_(partial_match, fuzzy_match))
                query = query.order_by(desc(fuzzy_score))
            else:
                query = query.filter(or_(full_text_match, partial_match, fuzzy_match))
                partial_score = sum(
                    case(
                        (Product.name.ilike(f"{term}%", escape="\\"), 2.0),
                        (Product.name.ilike(contains_pattern(term), escape="\\"), 1.0),
                        (Product.description.ilike(contains_pattern(term), escape="\\"), 0.5),
                        else_=0.0,
                    )
                    for term in search_terms
                )
                query = query.order_by(
                    desc(
                        func.ts_rank_cd(vector, terms)
                        + partial_score
                        + fuzzy_score
                    )
                )
        else:
            query = query.filter(or_(
                condition
                for term in search_terms
                for condition in (
                    Product.name.ilike(contains_pattern(term), escape="\\"),
                    Product.description.ilike(contains_pattern(term), escape="\\"),
                )
            ))



    # Minimum price filter

    if min_price is not None:

        query = query.filter(
            Product.price >= min_price
        )



    # Maximum price filter

    if max_price is not None:

        query = query.filter(
            Product.price <= max_price
        )



    # Stock filter

    if stock_available is True:

        query = query.filter(
            Product.stock > 0
        )


    elif stock_available is False:

        query = query.filter(
            Product.stock == 0
        )



    return paginate(
        query,
        page,
        limit
    )



def get_single_product(
    db: Session,
    product_id: int
):

    return get_product_by_id(
        db,
        product_id
    )



def update_existing_product(
    db: Session,
    product_id: int,
    product_data: ProductUpdate
):

    product = get_product_by_id(
        db,
        product_id
    )


    if not product:

        return None



    update_data = product_data.model_dump(
        exclude_unset=True
    )


    for key, value in update_data.items():

        setattr(
            product,
            key,
            value
        )



    db.commit()

    db.refresh(product)


    return product



def remove_product(
    db: Session,
    product_id: int
):

    product = get_product_by_id(
        db,
        product_id
    )

    if not product:
        return False

    has_order_history = (
        db.query(OrderItem.id)
        .filter(OrderItem.product_id == product_id)
        .first()
    )
    if has_order_history:
        raise ProductHasOrderHistoryError(
            "This product is part of an existing order and cannot be deleted. "
            "Set its stock to 0 to stop new sales while preserving order history."
        )

    return delete_product(
        db,
        product
    )