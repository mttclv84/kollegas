from rest_framework.permissions import BasePermission


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.livello_accesso == 'admin'


class IsAdminOrHO(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.livello_accesso in ('admin', 'ho')


class IsAdminOrHOOrArea(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.livello_accesso in ('admin', 'ho', 'area')


class IsStore(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.livello_accesso == 'store'


class CanManageUsers(BasePermission):
    """Admin e HO possono gestire tutti gli utenti; Store solo del proprio store."""
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.livello_accesso in ('admin', 'ho', 'store')

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.livello_accesso in ('admin', 'ho'):
            return True
        if user.livello_accesso == 'store':
            return obj.store_id == user.store_id
        return False
