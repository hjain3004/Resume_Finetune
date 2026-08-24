import copy

import pytest

from src.profile import load_profile
from src.tailor.profile_views import ProfileViewError, parse_selection, selection_to_dict


@pytest.fixture
def catalog():
    return selection_to_dict(load_profile("config/master_profile.yaml").for_selection("backend"))


@pytest.mark.parametrize("mutation", [
    lambda x: x["projects"].append(copy.deepcopy(x["projects"][0])),
    lambda x: x["experiences"].append(copy.deepcopy(x["projects"][0])),
    lambda x: x["bullets"].__setitem__(0, {**x["bullets"][0], "claim_type": "invented"}),
    lambda x: x["variants"].append(copy.deepcopy(x["variants"][0])),
    lambda x: x["variants"][0]["projects"].append("unknown"),
    lambda x: x["variants"][0]["bullet_order"].append("unknown"),
    lambda x: x["variants"][0].__setitem__("experience_order", list(reversed(x["variants"][0]["experience_order"]))),
    lambda x: x["variants"][0].__setitem__("experience_bullet_counts", [[x["variants"][0]["experience_order"][0], 0]]),
])
def test_selection_parser_rejects_tampered_catalog(catalog, mutation):
    mutation(catalog)
    with pytest.raises(ProfileViewError):
        parse_selection(catalog)


def test_selection_parser_rejects_boolean_or_unknown_experience_count(catalog):
    catalog["variants"][0]["experience_bullet_counts"][0][1] = True
    with pytest.raises(ProfileViewError):
        parse_selection(catalog)
