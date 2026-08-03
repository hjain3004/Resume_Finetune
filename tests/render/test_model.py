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


def test_render_bullet_emphasis_defaults_to_empty():
    bullet = RenderBullet(bullet_id="b1", text="Built an event store.")
    assert bullet.emphasis == ()


def test_render_bullet_carries_emphasis_spans():
    bullet = RenderBullet(bullet_id="b1", text="Cut p99 by 40%.", emphasis=((4, 7),))
    assert bullet.text[4:7] == "p99"

