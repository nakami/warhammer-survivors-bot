import tkinter as tk

import pytest

from warhammer_survivors_bot.gui_charts import LiveChart


@pytest.fixture
def root():
    r = tk.Tk()
    r.withdraw()
    yield r
    r.destroy()


def test_auto_scale_and_fixed_scale(root) -> None:
    chart = LiveChart(root, "On screen", ["Enemies", "XP"])
    chart.add([37, 4], t=0.0)
    assert chart._y_max() == 50
    chart.add([140, 4], t=1.0)
    assert chart._y_max() == 200
    fixed = LiveChart(root, "Health", ["Health"], y_max=100)
    fixed.add([250], t=0.0)
    assert fixed._y_max() == 100


def test_gaps_and_old_points_draw_without_error(root) -> None:
    import time
    chart = LiveChart(root, "Health and risk", ["Health", "Risk"], y_max=100)
    now = time.monotonic()
    for i in range(400):  # 200 s of samples, with a gap in the middle
        values = [None, None] if 150 < i < 170 else [90 - i * 0.1, i % 50]
        chart.add(values, t=now - (400 - i) * 0.5)
    chart.redraw()  # must not raise; draws lines, end labels, legend
    assert chart.find_all()
