"""Группа H: медиана, перцентили, отсев выбросов и сборка подсказки.

Числа здесь — Decimal и только Decimal: подсказанная цена попадает в смету
через ту же границу домена, что и введённая руками, и половина копейки в ней
недопустима ровно так же.
"""

from datetime import date
from decimal import Decimal as D

import pytest

from smeta_prices import (
    MIN_FOR_MEDIAN,
    MIN_FOR_SPREAD,
    Hint,
    PricePoint,
    from_history,
    median,
    outlier_bounds,
    percentile_25,
    percentile_75,
    without_outliers,
)


def prices(*values):
    return [D(value) for value in values]


# --- Медиана ---


def test_median_of_an_odd_sample_is_an_observed_price():
    assert median(prices("350", "380", "400")) == D("380")


def test_median_of_an_even_sample_is_the_middle_of_two_and_rounds_to_kopecks():
    """Иначе «медиана» зависела бы от того, какую из двух середин взяли."""
    assert median(prices("350", "381")) == D("365.50")
    assert median(prices("350.00", "350.01")) == D("350.01")  # HALF_UP, как везде


def test_median_ignores_the_order_it_was_given_in():
    assert median(prices("400", "350", "380")) == median(prices("350", "380", "400"))


def test_median_of_nothing_is_an_error_not_a_zero():
    with pytest.raises(ValueError, match="пустого"):
        median([])


# --- Перцентили: ближайший ранг, без интерполяции ---


def test_percentiles_return_prices_that_were_actually_seen():
    """Интерполяция синтезировала бы цену, которой никто не называл."""
    sample = prices("100", "200", "300", "400", "500", "600", "700", "800")
    assert percentile_25(sample) in sample
    assert percentile_75(sample) in sample
    assert percentile_25(sample) == D("200")
    assert percentile_75(sample) == D("600")


@pytest.mark.parametrize("size", range(1, 13))
def test_the_p75_shortcut_matches_the_nearest_rank_formula(size):
    """p75 считается как n − n//4, чтобы обойтись без умножения (ADR-002)."""
    sample = [D(value) for value in range(1, size + 1)]
    expected = sample[-(-(size * 3) // 4) - 1]
    assert percentile_75(sample) == expected


def test_a_single_price_is_its_own_quartiles():
    assert percentile_25(prices("380")) == percentile_75(prices("380")) == D("380")


# --- Выбросы ---


def test_bounds_widen_by_one_and_a_half_spreads():
    sample = prices("100", "200", "300", "400", "500", "600", "700", "800")
    low, high = outlier_bounds(sample)
    assert (low, high) == (D("-400.00"), D("1200.00"))


def test_an_absurd_price_falls_outside_the_bounds():
    sample = prices("350", "360", "370", "380", "390", "400", "410", "3800")
    assert D("3800") not in without_outliers(sample)
    assert len(without_outliers(sample)) == 7


def test_a_small_sample_is_returned_untouched():
    """Отсев на трёх точках выбрасывал бы данные, а не выбросы."""
    small = prices("350", "380", "3800")
    assert without_outliers(small) == small
    with pytest.raises(ValueError, match=str(MIN_FOR_SPREAD)):
        outlier_bounds(small)


# --- Подсказка ---


def point(price, day, spoken="мешок"):
    return PricePoint(price=D(price), on=date(2026, 3, day), unit_spoken=spoken)


def test_no_history_means_no_hint_at_all():
    """Молчание, а не «нет данных»: строка без цены и так видна с причиной."""
    assert from_history([]) is None


def test_the_hint_leads_with_the_most_recent_price():
    hint = from_history([point("350", 1), point("380", 12), point("370", 5)])
    assert isinstance(hint, Hint)
    assert (hint.last, hint.on, hint.times) == (D("380"), date(2026, 3, 12), 3)
    assert hint.unit_spoken == "мешок"


def test_the_median_appears_only_from_three_entries():
    assert from_history([point("350", 1), point("380", 2)]).median is None
    assert from_history([point("350", 1), point("380", 2), point("370", 3)]).median == D("370")
    assert MIN_FOR_MEDIAN == 3


def test_one_entry_is_still_a_hint():
    hint = from_history([point("380", 12)])
    assert (hint.last, hint.times, hint.median) == (D("380"), 1, None)
    # У одной точки разброса нет, и это видно по совпадению границ, а не по
    # None: «от 380 до 380» — правда, просто показывать её незачем.
    assert (hint.low, hint.high) == (D("380"), D("380"))


def test_the_spread_is_observed_prices_not_computed_ones():
    """Ровно тот случай, из-за которого написан ADR-026.

    История 450 / 700 / 1100 отвечала «1100» — правду про последнюю покупку и
    неправду про то, сколько это стоит.
    """
    hint = from_history([point("450", 1), point("700", 5), point("1100", 12)])
    assert (hint.low, hint.high) == (D("450"), D("1100"))
    assert hint.last == D("1100")
    # Обе границы обязаны быть среди названных цен: интерполяции здесь нет
    # и быть не может, иначе подсказка назовёт цену, которой не было.
    assert {hint.low, hint.high} <= {D("450"), D("700"), D("1100")}


def test_prices_named_on_one_day_have_no_last_one():
    """В истории нет времени точнее дня, и придумывать порядок мы не будем."""
    hint = from_history([point("450", 5), point("1100", 5)])
    assert hint.last is None
    assert (hint.low, hint.high, hint.times) == (D("450"), D("1100"), 2)
    # Равные цены того же дня двусмысленности не создают.
    assert from_history([point("450", 5), point("450", 5)]).last == D("450")
    # Двусмысленность только в самом свежем дне: старые цены порядка не портят.
    assert from_history([point("450", 1), point("700", 2), point("1100", 5)]).last == D("1100")


def test_the_spread_needs_no_threshold_unlike_the_quartiles():
    """Две точки — уже разброс, но ещё не медиана и не квартили (ADR-018).

    Порог нужен вычисленному числу. Минимум и максимум не вычислены: их
    называл человек, и с двух точек они честны ровно так же, как с двадцати.
    """
    hint = from_history([point("450", 1), point("1100", 2)])
    assert (hint.low, hint.high, hint.median) == (D("450"), D("1100"), None)
    assert MIN_FOR_MEDIAN == 3
    assert MIN_FOR_SPREAD == 8, "порог квартилей на разброс не распространяется"
