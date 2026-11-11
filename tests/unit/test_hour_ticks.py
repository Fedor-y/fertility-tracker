from datetime import date,timedelta
from zoneinfo import ZoneInfo
import pytest
from test_chart_projection import chart
from healthtracker.application.chart_projection import project_chart,day_start


@pytest.mark.parametrize('day,zone,missing,repeated',[
    (date(2026,3,29),'Europe/Berlin',2,None),
    (date(2026,10,25),'Europe/Berlin',None,2),
    (date(2026,10,4),'Australia/Lord_Howe',2,None),
])
def test_hour_ticks_are_real_whole_local_hours_on_dst(day,zone,missing,repeated):
    zone=ZoneInfo(zone);data=chart(start=day,zone=zone)
    result=project_chart(data);origin=day_start(day,zone)
    ticks=[t for t in result['axis']['ticks'] if t['x']<result['axis']['max']]
    hours=[]
    assert all(b['x']>a['x'] for a,b in zip(ticks,ticks[1:]))
    for tick in ticks:
        local=(origin+timedelta(seconds=tick['x'])).astimezone(zone)
        assert local.minute==0 and local.second==0
        assert tick['text']==local.strftime('%d.%m\n%H:%M %z')
        hours.append(local.hour)
    if missing is not None:assert missing not in hours
    if repeated is not None:assert hours.count(repeated)==2
