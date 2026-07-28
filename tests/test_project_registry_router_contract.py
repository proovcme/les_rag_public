from proxy.routers.datasets import router


def test_project_registry_routes_are_registered_read_only_where_expected():
    routes = {
        (route.path, method)
        for route in router.routes
        for method in getattr(route, "methods", set())
    }

    assert ("/api/rag/datasets/{dataset_id}/table-registry/build", "POST") in routes
    assert ("/api/rag/datasets/{dataset_id}/table-registry/summary", "GET") in routes
    assert ("/api/rag/datasets/{dataset_id}/tables/search", "GET") in routes
    assert ("/api/rag/datasets/{dataset_id}/tables/{table_id}", "GET") in routes
    assert ("/api/rag/datasets/{dataset_id}/document-registry/build", "POST") in routes
    assert ("/api/rag/datasets/{dataset_id}/document-registry", "GET") in routes
    assert ("/api/rag/datasets/{dataset_id}/virtual-volume", "GET") in routes
