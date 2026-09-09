import inspect
from typing import Any, Dict, List, Optional, Type, Union
from fastapi import HTTPException, status, Query, Request
from pydantic import BaseModel, Field
from tortoise.expressions import Q


# --- Schema Declarations for Bulk Operations ---

class BulkDeleteSchema(BaseModel):
    """Schema for receiving lookup values in bulk delete body."""
    keys: List[Union[int, str]] = Field(
        ..., 
        description="List of primary keys, IDs, or lookup field values to delete (e.g. ['id1', 'id2'])"
    )


class PaginatedResponse(BaseModel):
    """Envelope response structure for paginated lists."""
    count: int
    page: int
    page_size: int
    total_pages: int
    results: List[Any]


# --- Extended Mixins ---

class PermissionMixin:
    """Provides granular, action-level permission checking across HTTP & WebSockets."""
    
    action_permissions: Dict[str, List[Any]] = {}

    def get_permissions(self, action_name: str) -> List[Any]:
        if hasattr(self, "action_permissions") and action_name in self.action_permissions:
            return self.action_permissions[action_name]
        return getattr(self, "permission_classes", [])

    async def check_permissions(self, action_name: str, request: Optional[Request] = None):
        """
        Executes permissions defined for the specified action name dynamically.
        Inspects signature to support: (request), (request, view), or (user).
        """
        permissions = self.get_permissions(action_name)
        if not permissions:
            return

        user = getattr(request.state, "user", None) if request and hasattr(request, "state") else None

        for perm_cls in permissions:
            perm = perm_cls() if isinstance(perm_cls, type) else perm_cls

            if hasattr(perm, "has_permission"):
                sig = inspect.signature(perm.has_permission)
                params = list(sig.parameters.keys())

                if "user" in params and "request" not in params:
                    res = perm.has_permission(user)
                elif len(params) >= 2 and "view" in params:
                    res = perm.has_permission(request, self)
                elif len(params) == 1:
                    res = perm.has_permission(request)
                else:
                    try:
                        res = perm.has_permission(request, self)
                    except TypeError:
                        res = perm.has_permission(request)

                if inspect.iscoroutine(res) or inspect.isawaitable(res):
                    is_allowed = await res
                else:
                    is_allowed = res
            else:
                is_allowed = True

            if not is_allowed:
                if not user and request:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Authentication credentials were not provided."
                    )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission denied for action '{action_name}'"
                )


class ListModelMixin(PermissionMixin):
    """Network-Agnostic List Mixin supporting search, filter, ordering, and pagination."""
    
    page_size: int = 10

    def get_queryset(self):
        return self.model.all()

    def filter_queryset(self, queryset, search: Optional[str] = None, ordering: Optional[str] = None, filters: Optional[Dict[str, Any]] = None):
        if ordering:
            queryset = queryset.order_by(ordering)

        if search and hasattr(self, "search_fields") and self.search_fields:
            search_query = Q()
            for field in self.search_fields:
                search_query |= Q(**{f"{field}__icontains": search})
            queryset = queryset.filter(search_query)

        if filters:
            queryset = queryset.filter(**filters)

        return queryset

    async def list_action(
        self, 
        request: Optional[Request] = None,
        search: Optional[str] = Query(None, description="Search term across search fields"),
        ordering: Optional[str] = Query(None, description="Ordering field (e.g. -created_at)"),
        page: int = Query(1, ge=1, description="Page number"),
        page_size: int = Query(10, ge=1, le=100, description="Items per page"),
        **extra_filters: Any
    ):
        await self.check_permissions("list", request)
        
        queryset = self.get_queryset()
        queryset = self.filter_queryset(queryset, search=search, ordering=ordering, filters=extra_filters)

        total_count = await queryset.count()
        offset = (page - 1) * page_size
        results = await queryset.offset(offset).limit(page_size)
        total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1

        return {
            "count": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "results": results
        }


class CreateModelMixin(PermissionMixin):
    """Network-Agnostic Create Mixin supporting single & bulk creation."""

    async def create_action(self, payload: dict, request: Optional[Request] = None):
        await self.check_permissions("create", request)
        try:
            instance = await self.model.create(**payload)
            return instance
        except (ValueError, TypeError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid data format: {str(e)}"
            )

    async def bulk_create_action(self, payloads: List[dict], request: Optional[Request] = None):
        await self.check_permissions("bulk_create", request)
        try:
            instances = [self.model(**payload) for payload in payloads]
            await self.model.bulk_create(instances)
            return instances
        except (ValueError, TypeError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid bulk create data: {str(e)}"
            )


class RetrieveModelMixin(PermissionMixin):
    """Network-Agnostic Retrieve Mixin supporting multi-lookup fields."""

    async def retrieve_action(self, lookup_data: Dict[str, Any], request: Optional[Request] = None):
        await self.check_permissions("retrieve", request)
        try:
            return await self.model.filter(**lookup_data).first()
        except Exception:
            return None


class UpdateModelMixin(PermissionMixin):
    """Network-Agnostic Update Mixin with single & bulk updates."""
    
    lookup_field: str = "id"

    async def update_action(self, lookup_data: Dict[str, Any], update_payload: Dict[str, Any], request: Optional[Request] = None):
        await self.check_permissions("update", request)
        try:
            instance = await self.model.filter(**lookup_data).first()
            if not instance:
                return None
            
            for key, value in update_payload.items():
                setattr(instance, key, value)
                
            await instance.save()
            return instance
        except Exception:
            return None

    async def bulk_update_action(self, payloads: List[Dict[str, Any]], request: Optional[Request] = None):
        await self.check_permissions("bulk_update", request)
        updated_instances = []
        for payload in payloads:
            lookup_val = payload.get(self.lookup_field)
            if lookup_val is None:
                continue
            
            update_data = {k: v for k, v in payload.items() if k != self.lookup_field}
            updated = await self.update_action({self.lookup_field: lookup_val}, update_data, request)
            if updated:
                updated_instances.append(updated)
        return updated_instances


class DestroyModelMixin(PermissionMixin):
    """Network-Agnostic Destroy Mixin supporting single & bulk deletion."""
    
    lookup_field: str = "id"

    async def destroy_action(self, lookup_data: Dict[str, Any], request: Optional[Request] = None) -> bool:
        await self.check_permissions("destroy", request)
        try:
            instance = await self.model.filter(**lookup_data).first()
            if not instance:
                return False
            await instance.delete()
            return True
        except Exception:
            return False

    async def bulk_destroy_action(self, body: BulkDeleteSchema, request: Optional[Request] = None) -> Dict[str, Any]:
        await self.check_permissions("bulk_destroy", request)
        try:
            filter_kwargs = {f"{self.lookup_field}__in": body.keys}
            deleted_count = await self.model.filter(**filter_kwargs).delete()
            return {"deleted_count": deleted_count, "keys": body.keys}
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Bulk delete failed: {str(e)}"
            )