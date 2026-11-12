"""Общее подтверждение удаления сохранённой записи; без обращения к хранилищу."""
from PySide6.QtWidgets import QMessageBox
from healthtracker.application.diary import TITLES
from healthtracker.presentation.theme import style_message_box


def confirm_record_delete(parent, kind, *, date_text=None, unsaved=False):
    when = f' за {date_text}' if date_text else ''
    text = f'Удалить запись «{TITLES[kind]}»{when}? Это действие необратимо.'
    if unsaved:
        text += '\nНесохранённые изменения этой записи также будут потеряны.'
    box = QMessageBox(QMessageBox.Icon.Warning, 'Удаление записи', text,
                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, parent)
    box.button(QMessageBox.StandardButton.Yes).setText('Удалить')
    box.button(QMessageBox.StandardButton.No).setText('Отмена')
    box.setDefaultButton(QMessageBox.StandardButton.No)
    style_message_box(box)
    result = box.exec() == QMessageBox.StandardButton.Yes
    box.deleteLater()
    return result
