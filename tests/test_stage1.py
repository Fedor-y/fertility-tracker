"""ENV-01/02 и ограничения локального ресурса первого этапа."""

from PySide6.QtCore import QUrl

from healthtracker.presentation.chart import CHART_ROOT, resource_allowed
from healthtracker.presentation.main_window import MainWindow


def test_local_resource_policy():
    assert resource_allowed(QUrl.fromLocalFile(str(CHART_ROOT / "index.html")))
    assert resource_allowed(QUrl("qrc:///qtwebchannel/qwebchannel.js"))
    for url in ("https://example.com", "http://localhost", "file:///etc/passwd",
                "qrc:///other.js", "data:text/html,hello"):
        assert not resource_allowed(QUrl(url))


def test_env01_env02_local_chart_and_roundtrip(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.chart.bridge.is_ready, timeout=20000)
    assert window.chart.bridge.echarts_version == "6.0.0"
    assert "Записей пока нет" in window.status.text()
    # JS подтвердил nonce, присланный Python, версию ECharts и пустую серию.
    assert window.chart.profile.isOffTheRecord()


def test_missing_page_reports_failure(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    with qtbot.waitSignal(window.chart.failed, timeout=10000):
        window.chart.load(QUrl.fromLocalFile(str(CHART_ROOT / "missing.html")))


def test_external_navigation_is_rejected(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: window.chart.bridge.is_ready, timeout=20000)
    assert not window.chart.page().acceptNavigationRequest(
        QUrl("https://example.com"), None, True
    )
