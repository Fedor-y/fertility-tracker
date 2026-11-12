"""Запуск команды на отдельном виртуальном экране KWin, без окон на рабочем столе.

Пример: .venv/bin/python tests/manual/virtual_wayland.py .venv/bin/python -m pytest -q
Нужны уже установленные kwin_wayland и dbus-run-session; системные настройки не меняются.
"""
import os
from pathlib import Path
import shlex
import subprocess
import sys
from tempfile import TemporaryDirectory


def main(command):
    if not command:
        raise SystemExit('Укажите команду для запуска на виртуальном Wayland-экране.')
    with TemporaryDirectory(prefix='healthtracker-virtual-') as directory:
        root=Path(directory)
        runtime=root/'runtime';runtime.mkdir(mode=0o700)
        result_file=root/'exit-status'
        env=os.environ.copy()
        for key in ('DBUS_SESSION_BUS_ADDRESS','DISPLAY','WAYLAND_DISPLAY'):
            env.pop(key,None)
        env.update(XDG_RUNTIME_DIR=str(runtime),XDG_CONFIG_HOME=str(root/'config'),
                   XDG_CACHE_HOME=str(root/'cache'),XDG_DATA_HOME=str(root/'data'),
                   QT_QPA_PLATFORM='offscreen')
        script=root/'session.sh'
        script.write_text('#!/bin/sh\nexport QT_QPA_PLATFORM=wayland\n'+shlex.join(command)+
                          '\nresult=$?\nprintf "%s\\n" "$result" > '+shlex.quote(str(result_file))+
                          '\nexit "$result"\n')
        script.chmod(0o700)
        subprocess.run(['dbus-run-session','--','kwin_wayland','--virtual','--width','1920',
                        '--height','1080','--socket','healthtracker-test','--no-lockscreen',
                        '--no-global-shortcuts','--no-kactivities','--exit-with-session',str(script)],
                       env=env,timeout=600,check=False)
        if not result_file.exists():
            raise SystemExit('Команда не завершилась: см. журнал виртуального Wayland.')
        return int(result_file.read_text().strip())


if __name__=='__main__':
    raise SystemExit(main(sys.argv[1:]))
