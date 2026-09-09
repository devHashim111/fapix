import inspect
from typing import Any, Dict, List, Optional, Type, Callable, Union
from fastapi import Body, HTTPException, Query, Request, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from .base import BaseViewSet
from .tortoise.mixins import (
    ListModelMixin,
    CreateModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
    DestroyModelMixin,
)

# Optional security scheme so unauthenticated requests pass through FastAPI
security_optional = HTTPBearer(auto_error=False)


class APIView(BaseViewSet):
    """Base HTTP View Layer."""

    def get_lookup_dict(self, **kwargs: Any) -> Dict[str, Any]:
        """
        Extracts lookup values based on defined lookup_fields or lookup_field.
        """
        raw_fields = (
            getattr(self, "lookup_fields", None) 
            or getattr(self, "lookup_field", None) 
            or ["id"]
        )
        lookup_list = [raw_fields] if isinstance(raw_fields, str) else list(raw_fields)

        filtered_kwargs = {
            k: v for k, v in kwargs.items() 
            if v is not None and not isinstance(v, Request) and not isinstance(v, HTTPAuthorizationCredentials)
        }

        if not filtered_kwargs:
            return {}

        captured_val = next(iter(filtered_kwargs.values()), None)
        if captured_val is None:
            return {}

        lookup_data = {}
        for field in lookup_list:
            target_key = "id" if field == "pk" else field
            lookup_data[target_key] = captured_val

        return lookup_data

    async def get_user_from_request(self, request: Request, auth: Optional[HTTPAuthorizationCredentials] = None):
        """Extracts and authenticates user directly from request Authorization header or HTTPBearer credentials."""
        user = getattr(request.state, "user", None)
        if user:
            return user

        token = None
        if auth and auth.credentials:
            token = auth.credentials
        else:
            auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]

        if not token:
            return None

        try:
            from apps.auth.permissions import get_current_user
            
            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
            user = await get_current_user(creds)
            request.state.user = user
            return user
        except Exception:
            return None

    async def dispatch_permission_check(
        self, 
        request: Request, 
        action: str, 
        auth: Optional[HTTPAuthorizationCredentials] = None
    ):
        """Evaluates view permissions dynamically and authenticates the user."""
        perms = self.get_permissions(action)
        if not perms:
            return

        user = await self.get_user_from_request(request, auth=auth)

        for perm_cls in perms:
            perm = perm_cls() if isinstance(perm_cls, type) else perm_cls

            if hasattr(perm, "has_permission"):
                sig = inspect.signature(perm.has_permission)
                params = list(sig.parameters.keys())

                if "user" in params and "request" not in params:
                    res = perm.has_permission(user)
                elif len(params) >= 2:
                    res = perm.has_permission(request, self)
                elif len(params) == 1:
                    res = perm.has_permission(request)
                else:
                    res = perm.has_permission(user)

                if inspect.iscoroutine(res) or inspect.isawaitable(res):
                    is_allowed = await res
                else:
                    is_allowed = res
            else:
                is_allowed = True

            if not is_allowed:
                if not user:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Authentication credentials were not provided.",
                    )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission denied for action '{action}'",
                )


class GenericViewSet(APIView):
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
        auth_dep = Depends(security_optional) if needs_sec else None

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