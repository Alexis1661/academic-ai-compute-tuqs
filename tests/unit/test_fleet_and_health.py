def test_root_endpoint(client):
    """Verifies service identification and documentation links."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "Module 8: Token Usage & Quota Service (TUQS)" in data["module"]
    assert data["documentation"] == "/docs"


def test_health_check_probe(client):
    """
    Verifies that the /api/v1/health probe reports healthy database connectivity
    and loads the 32-node cluster summary.
    """
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "healthy"
    assert "cluster" in data
    assert data["cluster"]["total_nodes"] == 32
    assert data["cluster"]["healthy_nodes"] == 32
    assert data["cluster"]["total_vram_gb"] == 840  # (31 * 24) + (2 * 48) = 744 + 96 = 840 GB


def test_fleet_inventory_32_nodes_composition(client):
    """
    Verifies the hardware agnosticism requirement:
    Cluster contains exactly 32 nodes:
    - 31 workstations with 24 GB VRAM each
    - 1 central server with 2 x 48 GB GPUs (96 GB VRAM)
    """
    response = client.get("/api/v1/fleet")
    assert response.status_code == 200
    data = response.json()

    nodes = data["nodes"]
    assert len(nodes) == 32

    workstations = [n for n in nodes if n["node_type"] == "WORKSTATION"]
    servers = [n for n in nodes if n["node_type"] == "SERVER"]

    assert len(workstations) == 31
    for ws in workstations:
        assert ws["gpu_count"] == 1
        assert ws["vram_gb_per_gpu"] == 24
        assert ws["total_vram_gb"] == 24
        assert ws["status"] == "HEALTHY"

    assert len(servers) == 1
    srv = servers[0]
    assert srv["gpu_count"] == 2
    assert srv["vram_gb_per_gpu"] == 48
    assert srv["total_vram_gb"] == 96
    assert srv["status"] == "HEALTHY"
