"""Tests for Svitlo Yeah models."""

import datetime as dt

import pytest

from custom_components.svitlo_yeah.const import (
    CONF_CITY,
    CONF_HOUSE,
    CONF_STREET,
)
from custom_components.svitlo_yeah.models import (
    ConnectivityState,
    PlannedOutageEvent,
    PlannedOutageEventType,
    YasnoAddress,
    YasnoPlannedOutageDayStatus,
)
from tests.helpers import YASNO_KYIV_1_1, YASNO_KYIV_HOUSE, YASNO_KYIV_STREET


class TestYasnoPlannedOutageEventType:
    """Test YasnoPlannedOutageEventType enum."""

    def test_definite(self):
        """Test DEFINITE type."""
        assert PlannedOutageEventType.DEFINITE == "Definite"

    def test_not_planned(self):
        """Test NOT_PLANNED type."""
        assert PlannedOutageEventType.NOT_PLANNED == "NotPlanned"

    def test_emergency(self):
        """Test EMERGENCY type."""
        assert PlannedOutageEventType.EMERGENCY == "Emergency"

    def test_scheduled(self):
        """Test SCHEDULED type."""
        assert PlannedOutageEventType.SCHEDULED == "Scheduled"


class TestYasnoPlannedOutageDayStatus:
    """Test YasnoPlannedOutageDayStatus enum."""

    def test_schedule_applies(self):
        """Test STATUS_SCHEDULE_APPLIES."""
        assert YasnoPlannedOutageDayStatus.STATUS_SCHEDULE_APPLIES == "ScheduleApplies"

    def test_emergency_shutdowns(self):
        """Test STATUS_EMERGENCY_SHUTDOWNS."""
        assert (
            YasnoPlannedOutageDayStatus.STATUS_EMERGENCY_SHUTDOWNS
            == "EmergencyShutdowns"
        )

    def test_waiting_for_schedule(self):
        """Test STATUS_WAITING_FOR_SCHEDULE."""
        assert (
            YasnoPlannedOutageDayStatus.STATUS_WAITING_FOR_SCHEDULE
            == "WaitingForSchedule"
        )


class TestConnectivityState:
    """Test ConnectivityState enum."""

    def test_emergency(self):
        """Test STATE_EMERGENCY."""
        assert ConnectivityState.STATE_EMERGENCY == "emergency"

    def test_normal(self):
        """Test STATE_NORMAL."""
        assert ConnectivityState.STATE_NORMAL == "normal"

    def test_planned_outage(self):
        """Test STATE_PLANNED_OUTAGE."""
        assert ConnectivityState.STATE_PLANNED_OUTAGE == "planned_outage"


class TestYasnoPlannedOutageEvent:
    """Test YasnoPlannedOutageEvent dataclass."""

    def test_create_with_datetime(self):
        """Test creating event with datetime."""
        start = dt.datetime(2025, 1, 27, 10, 0, 0, tzinfo=dt.UTC)
        end = dt.datetime(2025, 1, 27, 12, 0, 0, tzinfo=dt.UTC)
        event = PlannedOutageEvent(
            event_type=PlannedOutageEventType.DEFINITE,
            start=start,
            end=end,
        )
        assert event.start == start
        assert event.end == end
        assert event.event_type == PlannedOutageEventType.DEFINITE
        assert event.all_day is False

    def test_create_with_date(self):
        """Test creating event with date."""
        start = dt.date(2025, 1, 27)
        end = dt.date(2025, 1, 27)
        event = PlannedOutageEvent(
            event_type=PlannedOutageEventType.EMERGENCY,
            start=start,
            end=end,
            all_day=True,
        )
        assert event.start == start
        assert event.end == end
        assert event.all_day is True

    def test_frozen(self):
        """Test that event is frozen."""
        event = PlannedOutageEvent(
            event_type=PlannedOutageEventType.DEFINITE,
            start=dt.datetime(2025, 1, 27, 10, 0, 0, tzinfo=dt.UTC),
            end=dt.datetime(2025, 1, 27, 12, 0, 0, tzinfo=dt.UTC),
        )
        with pytest.raises(AttributeError):
            # noinspection PyDataclass
            event.start = dt.datetime(2025, 1, 28, 10, 0, 0, tzinfo=dt.UTC)


class TestYasnoAddress:
    """Test YasnoAddress: the address of an entry, and its text."""

    def test_entry_without_a_city(self):
        """The street and the house of an entry give the address, with no city."""
        data = {
            **YASNO_KYIV_1_1,
            CONF_STREET: YASNO_KYIV_STREET,
            CONF_HOUSE: YASNO_KYIV_HOUSE,
        }

        address = YasnoAddress.from_entry_data(data)

        assert address == YasnoAddress(
            street=YASNO_KYIV_STREET, house=YASNO_KYIV_HOUSE, city=None
        )

    def test_entry_with_a_city(self):
        """A region with cities has the city in the address too."""
        data = {
            **YASNO_KYIV_1_1,
            CONF_CITY: "м. Дніпро",
            CONF_STREET: "вул. Грушевського Михайла",
            CONF_HOUSE: "1",
        }

        address = YasnoAddress.from_entry_data(data)

        assert address == YasnoAddress(
            city="м. Дніпро", street="вул. Грушевського Михайла", house="1"
        )

    # The keys of an entry that has no address: a group entry, an entry with the
    # street only, an entry with the house only, and an entry with the city only
    @pytest.mark.parametrize(
        "keys",
        [
            pytest.param({}, id="group_entry"),
            pytest.param({CONF_STREET: YASNO_KYIV_STREET}, id="without_a_house"),
            pytest.param({CONF_HOUSE: YASNO_KYIV_HOUSE}, id="without_a_street"),
            pytest.param(
                {CONF_CITY: "м. Дніпро", CONF_STREET: "вул. Шевченка"},
                id="city_and_street",
            ),
            pytest.param({CONF_CITY: "м. Дніпро"}, id="city_only"),
        ],
    )
    def test_entry_without_a_street_or_a_house_has_no_address(self, keys):
        """Both the street and the house make an address: else the entry has none."""
        assert YasnoAddress.from_entry_data({**YASNO_KYIV_1_1, **keys}) is None

    # The city, the street and the house as Yasno writes them, and the text. Yasno
    # writes some names with a space at the end, and the text has none.
    @pytest.mark.parametrize(
        ("city", "street", "house", "text"),
        [
            pytest.param(
                None,
                "вул. Сверстюка Євгена",
                YASNO_KYIV_HOUSE,
                f"вул. Сверстюка Євгена, {YASNO_KYIV_HOUSE}",
                id="without_a_city",
            ),
            pytest.param(
                None,
                "вул. Сверстюка Євгена ",
                YASNO_KYIV_HOUSE,
                f"вул. Сверстюка Євгена, {YASNO_KYIV_HOUSE}",
                id="without_a_city_and_a_space_at_the_end_of_the_street",
            ),
            pytest.param(
                "м. Дніпро",
                "вул. Грушевського Михайла",
                "1",
                "м. Дніпро, вул. Грушевського Михайла, 1",
                id="with_a_city",
            ),
            pytest.param(
                "м. Дніпро",
                "вул. Грушевського Михайла ",
                "1",
                "м. Дніпро, вул. Грушевського Михайла, 1",
                id="with_a_city_and_a_space_at_the_end_of_the_street",
            ),
            pytest.param(
                "м. Дніпро ",
                "вул. Шевченка ",
                "1 ",
                "м. Дніпро, вул. Шевченка, 1",
                id="a_space_at_the_end_of_each_name",
            ),
        ],
    )
    def test_text(self, city, street, house, text):
        """The text joins the city, the street and the house with a comma."""
        address = YasnoAddress(street=street, house=house, city=city)

        assert address.text == text

    def test_text_of_an_address_of_an_entry(self):
        """The address that an entry gives has the text of its street and its house."""
        data = {
            **YASNO_KYIV_1_1,
            CONF_CITY: "м. Дніпро",
            CONF_STREET: "вул. Шевченка ",
            CONF_HOUSE: "1",
        }

        address = YasnoAddress.from_entry_data(data)

        assert address is not None
        assert address.text == "м. Дніпро, вул. Шевченка, 1"
