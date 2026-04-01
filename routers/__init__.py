"""
API Routers — Jobs repo subset.
Lambda handlers import specific functions directly (e.g. from routers.documents import ...),
so we don't eagerly import all routers here to avoid missing-module errors.
"""
