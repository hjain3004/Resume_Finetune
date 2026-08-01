import dataclasses
import pytest
from src.render.model import RenderBullet, RenderEntry, RenderDoc


def test_render_entry_defaults_are_empty():
    entry = RenderEntry(entry_id="pc", heading="PeerChat", subheading="Go, gRPC")
    assert entry.date_range == ""
    assert entry.location == ""
    assert entry.bullets == ()


def test_render_doc_is_frozen():
    doc = RenderDoc(
        identity={"name": "Test User"},
        education=(),
        experience=(),
        projects=(),
        skills={"languages": ("Python",)},
        section_order=("Education", "Skills"),
        ats={},
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        doc.identity = {}


def test_render_bullet_carries_id_for_traceability():
    bullet = RenderBullet(bullet_id="pc_b01_event_sourcing", text="Built an event store.")
    assert bullet.bullet_id == "pc_b01_event_sourcing"
    assert bullet.text == "Built an event store."
