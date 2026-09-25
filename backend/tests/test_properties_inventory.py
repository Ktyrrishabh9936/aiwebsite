import pytest
from fastapi import HTTPException

from properties import clean_property, unit_specs


def test_apartment_inventory_is_grouped_and_total_is_derived():
    property_data = clean_property({
        "name": "Lake View Apartments",
        "category": "residential",
        "subtype": "Apartment",
        "container_kind": "project",
        "inventory_setup": {
            "mode": "unit_mix",
            "total_units": 999,
            "unit_mix": [
                {"tower": " Tower A ", "bhk": "2 BHK", "count": 40},
                {"tower": "Tower A", "bhk": "1 BHK", "count": 20},
                {"tower": "Tower B", "bhk": "2 BHK", "count": 30},
            ],
        },
    })
    setup = property_data["inventory_setup"]
    assert setup["total_units"] == 90
    assert setup["unit_mix"][0] == {"tower": "Tower A", "bhk": "2 BHK", "count": 40}


@pytest.mark.parametrize("rows", [
    [{"tower": "Tower A", "bhk": "2 BHK", "count": 2}, {"tower": "tower a", "bhk": "2 bhk", "count": 3}],
    [{"tower": "Tower A", "bhk": "2 BHK", "count": 0}],
    [{"tower": "", "bhk": "2 BHK", "count": 2}],
])
def test_invalid_tower_inventory_is_rejected(rows):
    with pytest.raises(HTTPException) as error:
        clean_property({"name": "Apartment", "inventory_setup": {"unit_mix": rows}})
    assert error.value.status_code == 400


def test_existing_manual_inventory_remains_valid():
    setup = {"mode": "manual", "total_units": 12}
    assert clean_property({"name": "Old project", "inventory_setup": setup})["inventory_setup"] == setup


def test_generates_separate_numbered_flats_and_price_ranges():
    project = clean_property({"name": "Lake View", "inventory_setup": {"unit_mix": [
        {"tower": "A", "bhk": "2 BHK", "count": 2, "start_number": "A-004", "price_min": "2000000", "price_max": "2400000"},
        {"tower": "A", "bhk": "1 BHK", "count": 1, "start_number": "A-101", "price_min": "1500000", "price_max": "1700000"},
    ]}})
    flats = unit_specs(project)
    assert [(unit["tower"], unit["unit_number"], unit["bhk"]) for unit in flats] == [
        ("A", "A-004", "2 BHK"), ("A", "A-005", "2 BHK"), ("A", "A-101", "1 BHK")]
    assert flats[0]["price_min_minor"] == 200000000
    assert flats[2]["price_min_minor"] == 150000000


def test_rejects_overlapping_flat_numbers_in_one_tower():
    project = clean_property({"name": "Lake View", "inventory_setup": {"unit_mix": [
        {"tower": "A", "bhk": "2 BHK", "count": 3, "start_number": "101"},
        {"tower": "A", "bhk": "1 BHK", "count": 1, "start_number": "103"},
    ]}})
    with pytest.raises(HTTPException) as error:
        unit_specs(project)
    assert error.value.status_code == 400


def test_floor_numbering_with_same_bhk_in_multiple_stacks():
    project = clean_property({"name": "Lake View", "inventory_setup": {"unit_mix": [
        {"tower": "A", "bhk": "2 BHK", "count": 3, "start_number": "101", "number_step": 100},
        {"tower": "A", "bhk": "2 BHK", "count": 3, "start_number": "102", "number_step": 100},
    ]}})
    assert [unit["unit_number"] for unit in unit_specs(project)] == ["101", "201", "301", "102", "202", "302"]
