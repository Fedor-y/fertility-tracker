"""Неизменяемая JSON-часть доставки, подготовленная до GUI/WebChannel."""
from dataclasses import dataclass,field,fields,is_dataclass
from datetime import date,datetime
from enum import Enum
import json,math

from healthtracker.application.chart_projection import project_chart
from healthtracker.domain.charts import PreparedChart


def data_value(value):
    if value is None or type(value) in (bool,int,str):return value
    if type(value) is float and math.isfinite(value):return value
    if isinstance(value,Enum):return value.value
    if isinstance(value,(datetime,date)):return value.isoformat()
    if isinstance(value,tuple):return [data_value(item) for item in value]
    if is_dataclass(value):return {field.name:data_value(getattr(value,field.name)) for field in fields(value)}
    raise ValueError('Недопустимое поле сообщения графика.')


@dataclass(frozen=True,slots=True)
class PreparedChartData:
    chart: PreparedChart
    projection_json: str | None
    json_text: str = field(init=False)

    @classmethod
    def prepare(cls,chart,projection_json=None):
        return cls(chart,projection_json)

    def __post_init__(self):
        chart,projection_json=self.chart,self.projection_json
        if not isinstance(chart,PreparedChart):raise ValueError('Нужен подготовленный график.')
        data={field.name:data_value(getattr(chart,field.name)) for field in fields(chart) if field.name!='context'}
        data['view']=json.loads(projection_json) if projection_json is not None else project_chart(chart)
        data['context']={'now':chart.context.now.isoformat(),'zone':str(chart.context.zone)}
        object.__setattr__(self,'json_text',json.dumps(data,ensure_ascii=False,allow_nan=False))
