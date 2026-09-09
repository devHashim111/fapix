from typing import Any, Dict, List, Optional, Type, Union, Callable
from pydantic import BaseModel
from tortoise.models import Model
from tortoise.queryset import QuerySet


class DefaultPagination:
    """Default Pagination Handler for BaseViewSet."""

    def __init__(self, page_size: int = 10, max_page_size: int = 100):
        self.page_size = page_size
        self.max_page_size = max_page_size

    async def paginate_queryset(
        self, queryset: QuerySet, page: int = 1, page_size: Optional[int] = None
    ) -> Dict[str, Any]:
        size = page_size or self.page_size
        size = min(size, self.max_page_size)
        page = max(1, page)

        total_count = await queryset.count()
        offset = (page - 1) * size
        results = await queryset.offset(offset).limit(size)
        total_pages = (total_count + size - 1) // size if total_count > 0 else 1

        return {
            "count": total_count,
            "page": page,
            "page_size": size,
            "total_pages": total_pages,
            "results": results,
        }


class BaseViewSet:
    """Network-Agnostic Base ViewSet for HTTP and WebSockets."""

    model: Optional[Type[Model]] = None
    schema: Optional[Type[BaseModel]] = None

    action_schemas: Dict[str, Type[BaseModel]] = {}

    permission_classes: List[Any] = []
    action_permissions: Dict[str, List[Any]] = {}

    lookup_fields: List[str] = ["id"]
    search_fields: List[str] = []
    filterset_fields: List[str] = []
    ordering_fields: List[str] = []
    default_ordering: List[str] = []

    pagination_class: Optional[Type[Any]] = DefaultPagination
    page_size: int = 10
    max_page_size: int = 100

    def get_schema(self, action: str) -> Optional[Type[BaseModel]]:
        return self.action_schemas.get(action, self.schema)

    def get_permissions(self, action: str) -> List[Any]:
        # 1. Explicit class-level override for this action wins outright.
        if action in self.action_permissions:
            return self.action_permissions[action]

        # 2. Fall back to permission_classes stamped directly onto the
        #    action method by the @permission_classes decorator (used on
        #    @action-decorated custom methods). Without this, decorating
        #    a single action with @permission_classes([...]) would show
        #    the lock icon (schema-time) but never be enforced (dispatch-time),
        #    since only this method's return value drives the actual check.
        handler = getattr(self, action, None)
        handler_perms = getattr(handler, "permission_classes", None)
        if handler_perms is not None:
            return handler_perms

        # 3. Class-level default.
        return self.permission_classes

    def get_queryset(self) -> QuerySet:
        if self.model is None:
            raise NotImplementedError(
                "ViewSet must define 'model' or override 'get_queryset()'"
            )
        return self.model.all()

    def filter_queryset(
        self,
        queryset: QuerySet,
        search: Optional[str] = None,
        ordering: Optional[Union[str, List[str]]] = None,
        params: Optional[Dict[str, Any]] = None,
        filters: Optional[Dict[str, Any]] = None,
        **extra_filters: Any
    ) -> QuerySet:
        params_dict = (params or {}).copy()

        if search is not None:
            params_dict["search"] = search

        if ordering is not None:
            params_dict["ordering"] = ordering

        if filters and isinstance(filters, dict):
            params_dict.update(filters)

        params_dict.update(extra_filters)

        if self.filterset_fields:
            filter_kwargs = {}

            for field in self.filterset_fields:
                if field in params_dict and params_dict[field] is not None:
                    filter_kwargs[field] = params_dict[field]

            if filter_kwargs:
                queryset = queryset.filter(**filter_kwargs)

        search_query = params_dict.get("search")

        if search_query and self.search_fields:
            from tortoise.expressions import Q

            search_kwargs = {
                f"{field}__icontains": search_query
                for field in self.search_fields
            }

            q_objects = [
                Q(**{key: value})
                for key, value in search_kwargs.items()
            ]

            if q_objects:
                combined_q = q_objects[0]

                for q in q_objects[1:]:
                    combined_q |= q

                queryset = queryset.filter(combined_q)

        ordering_val = params_dict.get("ordering")

        if ordering_val:
            if isinstance(ordering_val, str):
                ordering_list = [
                    item.strip()
                    for item in ordering_val.split(",")
                    if item.strip()
                ]
            else:
                ordering_list = list(ordering_val)

            if self.ordering_fields:
                valid_fields = set(self.ordering_fields)

                ordering_list = [
                    item
                    for item in ordering_list
                    if item.lstrip("-") in valid_fields
                ]

            if ordering_list:
                queryset = queryset.order_by(*ordering_list)

        elif self.default_ordering:
            queryset = queryset.order_by(*self.default_ordering)

        return queryset

    def build_lookup_kwargs(
        self,
        payload_or_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        lookup_kwargs = {}

        for field in self.lookup_fields:
            target_field = "id" if field == "pk" else field

            val = payload_or_params.get(target_field)
            if val is None:
                val = payload_or_params.get(field)

            if val is None and field in ["id", "pk"]:
                val = payload_or_params.get("id")
                if val is None:
                    val = payload_or_params.get("pk")

            if val is None:
                raise ValueError(
                    f"Missing required lookup parameter '{field}'"
                )

            lookup_kwargs[target_field] = val

        return lookup_kwargs

    async def paginate_queryset(
        self,
        queryset: QuerySet,
        page: int = 1,
        page_size: Optional[int] = None,
    ) -> Union[QuerySet, Dict[str, Any]]:
        if not self.pagination_class:
            return await queryset

        paginator = self.pagination_class(
            page_size=self.page_size,
            max_page_size=self.max_page_size,
        )

        return await paginator.paginate_queryset(
            queryset,
            page=page,
            page_size=page_size,
        )

    @classmethod
    def as_view(
        cls,
        actions: Optional[Dict[str, str]] = None,
        **initkwargs: Any,
    ) -> Callable:
        if actions is None:
            actions = {}

        instance = cls(**initkwargs)
        handlers = {}

        for method, action_name in actions.items():
            method = method.lower()

            endpoint_factory = getattr(
                instance,
                "get_endpoint_handler",
                None,
            )

            endpoint = None

            if endpoint_factory:
                try:
                    endpoint = endpoint_factory(action_name)
                except Exception:
                    endpoint = None

            if endpoint:
                handlers[method] = endpoint
                continue

            handler = getattr(instance, action_name, None)

            if handler:
                handlers[method] = handler

        async def view(
            request: Any,
            **kwargs: Any,
        ) -> Any:
            method = request.method.lower()
            handler = handlers.get(method)

            if not handler:
                from fastapi import HTTPException, status

                raise HTTPException(
                    status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
                    detail=(
                        f"Method '{method.upper()}' "
                        "not allowed on this endpoint."
                    ),
                )

            # Route through the same handler that get_endpoint_handler()
            # built (or, failing that, the raw method) so permission
            # checks and typed params behave the same as when this view
            # is registered through register_urlpatterns. This closure
            # is normally only introspected via `.cls`/`.actions` by
            # register_urlpatterns rather than called directly, but keep
            # it correct in case it's ever mounted as a route as-is.
            return await handler(
                request=request,
                **kwargs,
            )

        view.cls = cls
        view.actions = actions
        view.fapix_handlers = handlers

        return view