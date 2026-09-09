import inspect
from typing import Any, Dict, List, Optional, Type, Callable, Union

from fastapi import Body, HTTPException, Query, Request, Depends, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from .viewsets.base import BaseViewSet
from .viewsets.tortoise.mixins import (
    ListModelMixin,
    CreateModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
    DestroyModelMixin,
)
from apps.auth.permissions import security


def _lookup_fields(view: Any) -> List[str]:
    fields = (
        getattr(view, "lookup_fields", None)
        or getattr(view, "lookup_field", None)
        or ["id"]
    )
    return [fields] if isinstance(fields, str) else list(fields)


def _set_signature(
    endpoint: Callable,
    parameters: List[inspect.Parameter],
    return_annotation: Any = inspect.Signature.empty,
) -> Callable:
    clean_params = [
        p
        for p in parameters
        if p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    ]
    endpoint.__signature__ = inspect.Signature(
        parameters=clean_params,
        return_annotation=return_annotation,
    )
    return endpoint


def _request_parameter() -> inspect.Parameter:
    return inspect.Parameter(
        "request",
        inspect.Parameter.KEYWORD_ONLY,
        annotation=Request,
    )


def _auth_parameter() -> inspect.Parameter:
    return inspect.Parameter(
        "auth",
        inspect.Parameter.KEYWORD_ONLY,
        annotation=Optional[HTTPAuthorizationCredentials],
        default=Depends(security),
    )


def _lookup_parameters(view: Any) -> List[inspect.Parameter]:
    return [
        inspect.Parameter(
            field,
            inspect.Parameter.KEYWORD_ONLY,
            annotation=str,
        )
        for field in _lookup_fields(view)
    ]


def _get_lookup_values(view: Any, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    fields = _lookup_fields(view)

    for field in fields:
        if field in kwargs and kwargs[field] is not None:
            return {"id" if field == "pk" else field: kwargs[field]}

    for field in ("id", "pk", "slug"):
        if field in kwargs and kwargs[field] is not None:
            return {"id" if field == "pk" else field: kwargs[field]}

    return {}


class APIView(BaseViewSet):
    def get_lookup_dict(self, **kwargs: Any) -> Dict[str, Any]:
        return _get_lookup_values(self, kwargs)

    async def get_user_from_request(
        self,
        request: Request,
        auth: Optional[HTTPAuthorizationCredentials] = None,
    ):
        user = getattr(request.state, "user", None)
        if user:
            return user

        token = auth.credentials if auth and auth.credentials else None

        if not token:
            auth_header = (
                request.headers.get("Authorization")
                or request.headers.get("authorization")
            )
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ", 1)[1]

        if not token:
            return None

        try:
            from apps.auth.permissions import get_current_user

            credentials = HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials=token,
            )
            user = await get_current_user(credentials)
            request.state.user = user
            return user
        except Exception:
            return None

    async def dispatch_permission_check(
        self,
        request: Request,
        action: str,
        auth: Optional[HTTPAuthorizationCredentials] = None,
    ):
        perms = self.get_permissions(action)
        if not perms:
            return

        user = await self.get_user_from_request(request, auth=auth)

        for perm_cls in perms:
            perm = perm_cls() if isinstance(perm_cls, type) else perm_cls
            if not hasattr(perm, "has_permission"):
                continue

            sig = inspect.signature(perm.has_permission)
            params = list(sig.parameters.keys())

            if "user" in params and "request" not in params:
                result = perm.has_permission(user)
            elif len(params) >= 2:
                result = perm.has_permission(request, self)
            elif len(params) == 1:
                result = perm.has_permission(request)
            else:
                result = perm.has_permission(user)

            if inspect.isawaitable(result):
                result = await result

            if not result:
                if not user:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Authentication credentials were not provided.",
                    )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission denied for action '{action}'",
                )

    def get_endpoint_handler(self, action: str = "get") -> Optional[Callable]:
        handler = getattr(self, action, None)
        if not handler or not callable(handler):
            return None

        original_signature = inspect.signature(handler)
        parameters = [_request_parameter()]
        lookup_fields = set(_lookup_fields(self))
        existing_lookup_fields = set()

        for name, param in original_signature.parameters.items():
            if name in ("self", "request"):
                continue

            if name in lookup_fields:
                parameters.append(
                    inspect.Parameter(
                        name,
                        inspect.Parameter.KEYWORD_ONLY,
                        annotation=(
                            param.annotation
                            if param.annotation is not inspect.Parameter.empty
                            else str
                        ),
                        default=param.default,
                    )
                )
                existing_lookup_fields.add(name)
                continue

            if param.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue

            parameters.append(
                inspect.Parameter(
                    name,
                    inspect.Parameter.KEYWORD_ONLY,
                    annotation=(
                        param.annotation
                        if param.annotation is not inspect.Parameter.empty
                        else Any
                    ),
                    default=param.default,
                )
            )

        for parameter in _lookup_parameters(self):
            if parameter.name not in existing_lookup_fields:
                parameters.append(parameter)

        if self.get_permissions(action):
            parameters.append(_auth_parameter())

        async def endpoint(**kwargs: Any):
            request = kwargs.pop("request")
            auth = kwargs.pop("auth", None)
            await self.dispatch_permission_check(request, action, auth=auth)
            return await handler(request, **kwargs)

        endpoint.__name__ = f"{self.__class__.__name__}_{action}"

        return _set_signature(
            endpoint,
            parameters,
            original_signature.return_annotation,
        )

    async def dispatch(self, request: Request, *args: Any, **kwargs: Any):
        method = request.method.lower()
        handler = getattr(self, method, None)

        if not handler:
            raise HTTPException(
                status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
                detail=f"Method '{request.method}' not allowed.",
            )

        await self.dispatch_permission_check(request, method)
        return await handler(request, *args, **kwargs)


class GenericAPIView(APIView):
    def requires_auth(self, action: str) -> bool:
        return bool(self.get_permissions(action))

    def get_serializer_class(self, action: str = "default") -> Optional[Type[BaseModel]]:
        return self.get_schema(action)


class CreateAPIView(GenericAPIView, CreateModelMixin):
    def get_endpoint_handler(self, action: str = "create") -> Optional[Callable]:
        schema_cls = self.get_schema("create")
        needs_sec = self.requires_auth("create")
        data_annotation = (
            Union[schema_cls, List[schema_cls]]
            if schema_cls
            else dict
        )

        parameters = [
            _request_parameter(),
            inspect.Parameter(
                "data",
                inspect.Parameter.KEYWORD_ONLY,
                annotation=data_annotation,
                default=Body(...),
            ),
        ]

        if needs_sec:
            parameters.append(_auth_parameter())

        async def create_endpoint(**kwargs: Any):
            request = kwargs.pop("request")
            data = kwargs.pop("data")
            auth = kwargs.pop("auth", None)
            return await self.post(request, data, auth=auth)

        create_endpoint.__name__ = f"{self.__class__.__name__}_create"

        return _set_signature(
            create_endpoint,
            parameters,
            data_annotation,
        )

    async def post(
        self,
        request: Request,
        data: Any,
        auth: Optional[HTTPAuthorizationCredentials] = None,
    ):
        await self.dispatch_permission_check(request, "create", auth=auth)
        schema = self.get_schema("create")

        if isinstance(data, BaseModel):
            validated_data = data.model_dump()
        else:
            validated_data = schema(**data).model_dump() if schema else data

        instance = await self.create_action(
            validated_data,
            request=request,
        )

        return (
            schema.model_validate(instance, from_attributes=True)
            if schema
            else instance
        )


class ListAPIView(GenericAPIView, ListModelMixin):
    def get_endpoint_handler(self, action: str = "list") -> Optional[Callable]:
        needs_sec = self.requires_auth("list")

        parameters = [
            _request_parameter(),
            inspect.Parameter(
                "search",
                inspect.Parameter.KEYWORD_ONLY,
                annotation=Optional[str],
                default=Query(
                    None,
                    description="Search query parameter",
                ),
            ),
            inspect.Parameter(
                "ordering",
                inspect.Parameter.KEYWORD_ONLY,
                annotation=Optional[str],
                default=Query(
                    None,
                    description="Ordering parameter e.g. -created_at",
                ),
            ),
            inspect.Parameter(
                "page",
                inspect.Parameter.KEYWORD_ONLY,
                annotation=int,
                default=Query(
                    1,
                    ge=1,
                    description="Page number",
                ),
            ),
            inspect.Parameter(
                "page_size",
                inspect.Parameter.KEYWORD_ONLY,
                annotation=Optional[int],
                default=Query(
                    None,
                    ge=1,
                    description="Number of items per page",
                ),
            ),
        ]

        if needs_sec:
            parameters.append(_auth_parameter())

        async def list_endpoint(**kwargs: Any):
            request = kwargs.pop("request")
            auth = kwargs.pop("auth", None)

            return await self.get(
                request,
                search=kwargs.get("search"),
                ordering=kwargs.get("ordering"),
                page=kwargs.get("page", 1),
                page_size=kwargs.get("page_size"),
                auth=auth,
            )

        list_endpoint.__name__ = f"{self.__class__.__name__}_list"

        return _set_signature(
            list_endpoint,
            parameters,
        )

    async def get(
        self,
        request: Request,
        page: int = 1,
        page_size: Optional[int] = None,
        search: Optional[str] = None,
        ordering: Optional[str] = None,
        auth: Optional[HTTPAuthorizationCredentials] = None,
    ):
        await self.dispatch_permission_check(request, "list", auth=auth)

        effective_page_size = page_size or getattr(self, "page_size", 10)

        response_data = await self.list_action(
            request=request,
            page=page,
            page_size=effective_page_size,
            search=search,
            ordering=ordering,
        )

        schema = self.get_schema("list")

        if not schema:
            return response_data

        if isinstance(response_data, dict) and "results" in response_data:
            response_data["results"] = [
                schema.model_validate(
                    item,
                    from_attributes=True,
                )
                for item in response_data["results"]
            ]
            return response_data

        if isinstance(response_data, list):
            return [
                schema.model_validate(
                    item,
                    from_attributes=True,
                )
                for item in response_data
            ]

        return response_data


class RetrieveAPIView(GenericAPIView, RetrieveModelMixin):
    def get_endpoint_handler(self, action: str = "retrieve") -> Optional[Callable]:
        schema_cls = self.get_schema("retrieve")
        needs_sec = self.requires_auth("retrieve")

        parameters = [
            _request_parameter(),
            *_lookup_parameters(self),
        ]

        if needs_sec:
            parameters.append(_auth_parameter())

        async def retrieve_endpoint(**kwargs: Any):
            request = kwargs.pop("request")
            auth = kwargs.pop("auth", None)
            return await self.get(
                request,
                auth=auth,
                **kwargs,
            )

        retrieve_endpoint.__name__ = f"{self.__class__.__name__}_retrieve"

        return _set_signature(
            retrieve_endpoint,
            parameters,
            schema_cls or Any,
        )

    async def get(
        self,
        request: Request,
        slug: Optional[str] = None,
        pk: Optional[str] = None,
        id: Optional[str] = None,
        auth: Optional[HTTPAuthorizationCredentials] = None,
        **kwargs: Any,
    ):
        await self.dispatch_permission_check(
            request,
            "retrieve",
            auth=auth,
        )

        lookup_data = self.get_lookup_dict(
            slug=slug,
            pk=pk,
            id=id,
            **kwargs,
        )

        instance = await self.retrieve_action(
            lookup_data,
            request=request,
        )

        if not instance:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not found",
            )

        schema = self.get_schema("retrieve")

        return (
            schema.model_validate(
                instance,
                from_attributes=True,
            )
            if schema
            else instance
        )


class DestroyAPIView(GenericAPIView, DestroyModelMixin):
    def get_endpoint_handler(self, action: str = "destroy") -> Optional[Callable]:
        needs_sec = self.requires_auth("destroy")

        parameters = [
            _request_parameter(),
            *_lookup_parameters(self),
        ]

        if needs_sec:
            parameters.append(_auth_parameter())

        async def destroy_endpoint(**kwargs: Any):
            request = kwargs.pop("request")
            auth = kwargs.pop("auth", None)
            return await self.delete(
                request,
                auth=auth,
                **kwargs,
            )

        destroy_endpoint.__name__ = f"{self.__class__.__name__}_destroy"

        return _set_signature(
            destroy_endpoint,
            parameters,
        )

    async def delete(
        self,
        request: Request,
        slug: Optional[str] = None,
        pk: Optional[str] = None,
        id: Optional[str] = None,
        auth: Optional[HTTPAuthorizationCredentials] = None,
        **kwargs: Any,
    ):
        await self.dispatch_permission_check(
            request,
            "destroy",
            auth=auth,
        )

        lookup_data = self.get_lookup_dict(
            slug=slug,
            pk=pk,
            id=id,
            **kwargs,
        )

        success = await self.destroy_action(
            lookup_data,
            request=request,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not found",
            )

        return {"detail": "Deleted successfully"}


class UpdateAPIView(GenericAPIView, UpdateModelMixin):
    def get_endpoint_handler(self, action: str = "update") -> Optional[Callable]:
        schema_cls = self.get_schema("update")
        needs_sec = self.requires_auth("update")

        parameters = [
            _request_parameter(),
            inspect.Parameter(
                "data",
                inspect.Parameter.KEYWORD_ONLY,
                annotation=schema_cls or dict,
                default=Body(...),
            ),
            *_lookup_parameters(self),
        ]

        if needs_sec:
            parameters.append(_auth_parameter())

        async def update_endpoint(**kwargs: Any):
            request = kwargs.pop("request")
            data = kwargs.pop("data")
            auth = kwargs.pop("auth", None)
            return await self.put(
                request,
                data,
                auth=auth,
                **kwargs,
            )

        update_endpoint.__name__ = f"{self.__class__.__name__}_update"

        return _set_signature(
            update_endpoint,
            parameters,
            schema_cls or Any,
        )

    async def put(
        self,
        request: Request,
        data: Any,
        slug: Optional[str] = None,
        pk: Optional[str] = None,
        id: Optional[str] = None,
        auth: Optional[HTTPAuthorizationCredentials] = None,
        **kwargs: Any,
    ):
        await self.dispatch_permission_check(
            request,
            "update",
            auth=auth,
        )

        lookup_data = self.get_lookup_dict(
            slug=slug,
            pk=pk,
            id=id,
            **kwargs,
        )

        update_data = (
            data.model_dump()
            if isinstance(data, BaseModel)
            else data
        )

        instance = await self.update_action(
            lookup_data,
            update_data,
            request=request,
        )

        if not instance:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not found",
            )

        schema = self.get_schema("update")

        return (
            schema.model_validate(
                instance,
                from_attributes=True,
            )
            if schema
            else instance
        )

    async def patch(
        self,
        request: Request,
        data: Any,
        **kwargs: Any,
    ):
        return await self.put(
            request,
            data,
            **kwargs,
        )


class ListCreateAPIView(ListAPIView, CreateAPIView):
    def get_endpoint_handler(self, action: str) -> Optional[Callable]:
        if action == "list":
            return ListAPIView.get_endpoint_handler(self, "list")
        if action == "create":
            return CreateAPIView.get_endpoint_handler(self, "create")
        return super().get_endpoint_handler(action)


class RetrieveUpdateAPIView(RetrieveAPIView, UpdateAPIView):
    def get_endpoint_handler(self, action: str) -> Optional[Callable]:
        if action == "retrieve":
            return RetrieveAPIView.get_endpoint_handler(self, "retrieve")
        if action == "update":
            return UpdateAPIView.get_endpoint_handler(self, "update")
        return super().get_endpoint_handler(action)


class RetrieveDestroyAPIView(RetrieveAPIView, DestroyAPIView):
    def get_endpoint_handler(self, action: str) -> Optional[Callable]:
        if action == "retrieve":
            return RetrieveAPIView.get_endpoint_handler(self, "retrieve")
        if action == "destroy":
            return DestroyAPIView.get_endpoint_handler(self, "destroy")
        return super().get_endpoint_handler(action)


class RetrieveUpdateDestroyAPIView(
    RetrieveAPIView,
    UpdateAPIView,
    DestroyAPIView,
):
    def get_endpoint_handler(self, action: str) -> Optional[Callable]:
        if action == "retrieve":
            return RetrieveAPIView.get_endpoint_handler(self, "retrieve")
        if action == "update":
            return UpdateAPIView.get_endpoint_handler(self, "update")
        if action == "destroy":
            return DestroyAPIView.get_endpoint_handler(self, "destroy")
        return super().get_endpoint_handler(action)


class GenericViewSet(GenericAPIView):
    pass


class ReadOnlyModelViewSet(
    GenericViewSet,
    ListModelMixin,
    RetrieveModelMixin,
):
    pass

class ModelViewSet(
    GenericViewSet,
    ListModelMixin,
    CreateModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
    DestroyModelMixin,
):
    """DRF-style ModelViewSet over HTTP with Multi-Lookup & Querying support."""

    def requires_auth(self, action: str) -> bool:
        """Determines whether an action requires authentication based on view permissions."""
        perms = self.get_permissions(action)
        return bool(perms)

    def get_endpoint_handler(self, action: str) -> Callable:
        """
        Generates endpoint handlers with typed Pydantic signatures for request body, 
        query parameters, dynamic OpenAPI security schemes, and return types.
        """
        original_handler = getattr(self, action, None)
        if not original_handler:
            return None

        schema_cls = self.get_schema(action)
        needs_sec = self.requires_auth(action)
        auth_dep = Depends(security) if needs_sec else None

        if action == "list":
            if needs_sec:
                async def list_endpoint(
                    request: Request,
                    search: Optional[str] = Query(None, description="Search query parameter"),
                    ordering: Optional[str] = Query(None, description="Ordering parameter e.g. -created_at"),
                    page: int = Query(1, ge=1, description="Page number"),
                    page_size: Optional[int] = Query(None, ge=1, description="Number of items per page"),
                    auth: Optional[HTTPAuthorizationCredentials] = auth_dep,
                ):
                    return await self.list(
                        request=request, 
                        search=search, 
                        ordering=ordering, 
                        page=page, 
                        page_size=page_size, 
                        auth=auth
                    )
            else:
                async def list_endpoint(
                    request: Request,
                    search: Optional[str] = Query(None, description="Search query parameter"),
                    ordering: Optional[str] = Query(None, description="Ordering parameter e.g. -created_at"),
                    page: int = Query(1, ge=1, description="Page number"),
                    page_size: Optional[int] = Query(None, ge=1, description="Number of items per page"),
                ):
                    return await self.list(
                        request=request, 
                        search=search, 
                        ordering=ordering, 
                        page=page, 
                        page_size=page_size
                    )

            list_endpoint.__name__ = f"{self.__class__.__name__}_list"
            return list_endpoint

        if action == "create":
            if schema_cls:
                if needs_sec:
                    async def create_endpoint(
                        request: Request, 
                        data: Union[schema_cls, List[schema_cls]] = Body(...),  # type: ignore
                        auth: Optional[HTTPAuthorizationCredentials] = auth_dep,
                    ) -> Union[schema_cls, List[schema_cls]]:  # type: ignore
                        return await self._execute_create(request, data, auth=auth)
                else:
                    async def create_endpoint(
                        request: Request, 
                        data: Union[schema_cls, List[schema_cls]] = Body(...),  # type: ignore
                    ) -> Union[schema_cls, List[schema_cls]]:  # type: ignore
                        return await self._execute_create(request, data)

                create_endpoint.__name__ = f"{self.__class__.__name__}_create"
                return create_endpoint

        if action == "retrieve":
            if schema_cls:
                if needs_sec:
                    async def retrieve_endpoint(
                        request: Request,
                        slug: Optional[str] = None,
                        pk: Optional[str] = None,
                        id: Optional[str] = None,
                        auth: Optional[HTTPAuthorizationCredentials] = auth_dep,
                    ) -> schema_cls:  # type: ignore
                        return await self.retrieve(request, slug=slug, pk=pk, id=id, auth=auth)
                else:
                    async def retrieve_endpoint(
                        request: Request,
                        slug: Optional[str] = None,
                        pk: Optional[str] = None,
                        id: Optional[str] = None,
                    ) -> schema_cls:  # type: ignore
                        return await self.retrieve(request, slug=slug, pk=pk, id=id)

                retrieve_endpoint.__name__ = f"{self.__class__.__name__}_retrieve"
                return retrieve_endpoint

        if action == "update":
            if schema_cls:
                if needs_sec:
                    async def update_endpoint(
                        request: Request,
                        data: schema_cls = Body(...),  # type: ignore
                        slug: Optional[str] = None,
                        pk: Optional[str] = None,
                        id: Optional[str] = None,
                        auth: Optional[HTTPAuthorizationCredentials] = auth_dep,
                    ) -> schema_cls:  # type: ignore
                        return await self._execute_update(request, data, slug=slug, pk=pk, id=id, auth=auth)
                else:
                    async def update_endpoint(
                        request: Request,
                        data: schema_cls = Body(...),  # type: ignore
                        slug: Optional[str] = None,
                        pk: Optional[str] = None,
                        id: Optional[str] = None,
                    ) -> schema_cls:  # type: ignore
                        return await self._execute_update(request, data, slug=slug, pk=pk, id=id)

                update_endpoint.__name__ = f"{self.__class__.__name__}_update"
                return update_endpoint

        if action == "destroy":
            if needs_sec:
                async def destroy_endpoint(
                    request: Request,
                    slug: Optional[str] = None,
                    pk: Optional[str] = None,
                    id: Optional[str] = None,
                    auth: Optional[HTTPAuthorizationCredentials] = auth_dep,
                ):
                    return await self.destroy(request, slug=slug, pk=pk, id=id, auth=auth)
            else:
                async def destroy_endpoint(
                    request: Request,
                    slug: Optional[str] = None,
                    pk: Optional[str] = None,
                    id: Optional[str] = None,
                ):
                    return await self.destroy(request, slug=slug, pk=pk, id=id)

            destroy_endpoint.__name__ = f"{self.__class__.__name__}_destroy"
            return destroy_endpoint

        return original_handler

    async def _execute_create(
        self, 
        request: Request, 
        data: Any, 
        auth: Optional[HTTPAuthorizationCredentials] = None
    ):
        await self.dispatch_permission_check(request, "create", auth=auth)
        schema = self.get_schema("create")

        # 1. Handle Bulk Creation (List payload)
        if isinstance(data, list):
            validated_payloads = [
                item.model_dump() if isinstance(item, BaseModel) else item 
                for item in data
            ]

            if hasattr(self, "bulk_create_action"):
                instances = await self.bulk_create_action(validated_payloads, request=request)
            else:
                instances = [
                    await self.create_action(payload, request=request) 
                    for payload in validated_payloads
                ]

            if schema:
                return [schema.model_validate(inst, from_attributes=True) for inst in instances]
            return instances

        # 2. Handle Single Item Creation
        if isinstance(data, BaseModel):
            validated_data = data.model_dump()
        else:
            validated_data = schema(**data).model_dump() if schema else data

        instance = await self.create_action(validated_data, request=request)

        if schema:
            return schema.model_validate(instance, from_attributes=True)
        return instance

    async def create(
        self, 
        request: Request, 
        data: Union[Dict[str, Any], List[Dict[str, Any]]] = Body(...),
        auth: Optional[HTTPAuthorizationCredentials] = None,
    ):
        return await self._execute_create(request, data, auth=auth)

    async def list(
        self, 
        request: Request,
        search: Optional[str] = None,
        ordering: Optional[str] = None,
        page: int = 1,
        page_size: Optional[int] = None,
        auth: Optional[HTTPAuthorizationCredentials] = None,
    ):
        await self.dispatch_permission_check(request, "list", auth=auth)
        
        params = dict(request.query_params)
        search = search or params.pop("search", None)
        ordering = ordering or params.pop("ordering", None)
        page = page or params.pop("page", 1)
        
        effective_page_size = page_size or getattr(self, "page_size", 10)

        try:
            page = int(page)
        except (ValueError, TypeError):
            page = 1

        try:
            page_size = int(effective_page_size)
        except (ValueError, TypeError):
            page_size = getattr(self, "page_size", 10)

        for param_key in ("search", "ordering", "page", "page_size"):
            params.pop(param_key, None)

        response_data = await self.list_action(
            request=request,
            search=search,
            ordering=ordering,
            page=page,
            page_size=page_size,
            **params
        )

        schema = self.get_schema("list")
        if not schema:
            return response_data

        if isinstance(response_data, dict) and "results" in response_data:
            response_data["results"] = [
                schema.model_validate(item, from_attributes=True)
                for item in response_data["results"]
            ]
            return response_data
        elif isinstance(response_data, list):
            return [schema.model_validate(item, from_attributes=True) for item in response_data]

        return response_data

    async def retrieve(
        self, 
        request: Request, 
        slug: Optional[str] = None, 
        pk: Optional[str] = None, 
        id: Optional[str] = None,
        auth: Optional[HTTPAuthorizationCredentials] = None,
    ):
        await self.dispatch_permission_check(request, "retrieve", auth=auth)
        lookup_data = self.get_lookup_dict(slug=slug, pk=pk, id=id)

        instance = await self.retrieve_action(lookup_data, request=request)
        if not instance:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

        schema = self.get_schema("retrieve")
        if schema:
            return schema.model_validate(instance, from_attributes=True)
        return instance

    async def _execute_update(
        self,
        request: Request,
        data: Any,
        slug: Optional[str] = None,
        pk: Optional[str] = None,
        id: Optional[str] = None,
        auth: Optional[HTTPAuthorizationCredentials] = None,
    ):
        await self.dispatch_permission_check(request, "update", auth=auth)
        lookup_data = self.get_lookup_dict(slug=slug, pk=pk, id=id)

        if isinstance(data, BaseModel):
            update_data = data.model_dump()
        else:
            update_data = data

        instance = await self.update_action(lookup_data, update_data, request=request)
        if not instance:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

        schema = self.get_schema("update")
        if schema:
            return schema.model_validate(instance, from_attributes=True)
        return instance

    async def update(
        self, 
        request: Request, 
        data: Dict[str, Any] = Body(...), 
        slug: Optional[str] = None, 
        pk: Optional[str] = None, 
        id: Optional[str] = None,
        auth: Optional[HTTPAuthorizationCredentials] = None,
    ):
        return await self._execute_update(request, data, slug=slug, pk=pk, id=id, auth=auth)

    async def destroy(
        self, 
        request: Request, 
        slug: Optional[str] = None, 
        pk: Optional[str] = None, 
        id: Optional[str] = None,
        auth: Optional[HTTPAuthorizationCredentials] = None,
    ):
        await self.dispatch_permission_check(request, "destroy", auth=auth)
        lookup_data = self.get_lookup_dict(slug=slug, pk=pk, id=id)

        success = await self.destroy_action(lookup_data, request=request)
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

        return {"detail": "Deleted successfully"}