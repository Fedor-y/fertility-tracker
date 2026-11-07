from dataclasses import replace
from datetime import UTC, date, datetime
import json
from uuid import uuid4

import pytest

from healthtracker.domain.analytics import AnalysisContext
from healthtracker.domain.charts import (ChartMode, PreparedChart, ChartSeries, ChartPoint,
                                         SourceRef, SeriesKind, DefinitionRef)
from healthtracker.domain.answers import CognitiveAnswer, AnswerStatus
from healthtracker.domain.periods import DateRange
from healthtracker.presentation.chart_payload import ChartPayload


def chart():
    moment = datetime(2026, 11, 1, 12, tzinfo=UTC)
    answers = (CognitiveAnswer.numeric(0), CognitiveAnswer(AnswerStatus.NOT_ENGAGED),
               CognitiveAnswer(AnswerStatus.CANNOT_ASSESS))
    source = SourceRef('cognitive', 7, (DefinitionRef('learning', 1),), answers)
    point = ChartPoint(moment.date(), None, (source,), moment, moment, None, None, None, 0)
    return PreparedChart(DateRange(moment.date(), moment.date()), AnalysisContext(moment, UTC),
                         ChartMode.DAY, 3, (ChartSeries(SeriesKind.COGNITIVE, (point,), ()),), (), ())


def test_serializes_real_sources_special_answers_and_null_without_code():
    payload = ChartPayload.prepare(*(uuid4().hex for _ in range(3)), 1, chart())
    data = json.loads(payload.encode())
    assert data['protocol'] == 1 and data['kind'] == 'data'
    point = data['data']['series'][0]['points'][0]
    assert point['value'] is None
    assert point['utc_moment'] == '2026-11-01T12:00:00+00:00'
    assert point['sources'][0]['record_id'] == 7
    assert point['sources'][0]['cognitive_answers'] == [
        {'status': 'numeric', 'value': 0}, {'status': 'not_engaged', 'value': None},
        {'status': 'cannot_assess', 'value': None}]
    assert 'option' not in data and 'sql' not in data


@pytest.mark.parametrize('bad', ['', '<script>', 'x' * 32, 1, None])
def test_rejects_invalid_identifier(bad):
    with pytest.raises(ValueError):
        ChartPayload.prepare(bad, uuid4().hex, uuid4().hex, 1, chart())


@pytest.mark.parametrize('mode', list(ChartMode))
def test_preserves_modes_without_projection(mode):
    payload = ChartPayload.prepare(*(uuid4().hex for _ in range(3)), 1, replace(chart(), mode=mode))
    assert json.loads(payload.encode())['data']['mode'] == mode.value


def test_worker_prepared_data_preserves_protocol_without_gui_serialization(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from healthtracker.application.chart_serialization import PreparedChartData
    prepared_chart=chart();ids=tuple(uuid4().hex for _ in range(3))
    expected=json.loads(ChartPayload.prepare(*ids,1,prepared_chart).encode())
    with ThreadPoolExecutor(max_workers=1) as pool:
        prepared=pool.submit(PreparedChartData.prepare,prepared_chart).result(timeout=5)
    def fail(*args):raise AssertionError('Сериализация не должна повторяться в GUI')
    monkeypatch.setattr(PreparedChartData,'prepare',fail)
    assert json.loads(ChartPayload.prepare(*ids,1,prepared_chart,prepared_data=prepared).encode())==expected


def test_changed_projection_cannot_reuse_old_prepared_json():
    from healthtracker.application.chart_serialization import PreparedChartData
    from healthtracker.application.chart_projection import project_chart
    prepared_chart=chart();view=project_chart(prepared_chart)
    original=json.dumps(view);prepared=PreparedChartData.prepare(prepared_chart,original)
    view['caption']='Новая проекция';changed=json.dumps(view)
    payload=ChartPayload.prepare(*(uuid4().hex for _ in range(3)),1,prepared_chart,
                                 projection_json=changed,prepared_data=prepared)
    assert json.loads(payload.encode())['data']['view']['caption']=='Новая проекция'


def test_prepared_json_cannot_be_supplied_as_arbitrary_constructor_field():
    from healthtracker.application.chart_serialization import PreparedChartData
    with pytest.raises(TypeError):
        PreparedChartData(chart(),None,'{}')
