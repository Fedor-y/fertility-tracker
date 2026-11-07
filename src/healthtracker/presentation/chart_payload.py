"""Только данные подготовленного графика; без ECharts option и личных текстов."""
from dataclasses import dataclass
import json
import re

from healthtracker.domain.charts import PreparedChart
from healthtracker.application.chart_serialization import PreparedChartData

PROTOCOL_VERSION = 1


def identifier(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{32}", value) is not None


@dataclass(frozen=True, slots=True)
class ChartPayload:
    page_id: str
    request_id: str
    delivery_id: str
    sequence: int
    chart_json: str

    @classmethod
    def prepare(cls, page_id, request_id, delivery_id, sequence, chart, *, projection_json=None, prepared_data=None):
        if not all(identifier(v) for v in (page_id, request_id, delivery_id)):
            raise ValueError("Недопустимый идентификатор доставки.")
        if type(sequence) is not int or sequence < 1 or not isinstance(chart, PreparedChart):
            raise ValueError("Нужны подготовленный график и номер сообщения.")
        if not (isinstance(prepared_data,PreparedChartData) and prepared_data.chart is chart
                and prepared_data.projection_json is projection_json):
            prepared_data=PreparedChartData.prepare(chart,projection_json)
        return cls(page_id,request_id,delivery_id,sequence,prepared_data.json_text)

    def encode(self):
        metadata = json.dumps({'protocol': PROTOCOL_VERSION, 'kind': 'data',
                           'page_id': self.page_id, 'request_id': self.request_id,
                           'delivery_id': self.delivery_id, 'sequence': self.sequence},
                           ensure_ascii=False,allow_nan=False)
        return metadata[:-1]+', "data": '+self.chart_json+'}'
