// This file was generated with the assistance of an AI coding tool.
/********************************************************************************
 *                                                                              *
 * This file is part of Bonsai.                                                 *
 *                                                                              *
 * Bonsai is free software: you can redistribute it and/or modify               *
 * it under the terms of the GNU General Public License as published by         *
 * the Free Software Foundation, either version 3.0 of the License, or          *
 * (at your option) any later version.                                          *
 *                                                                              *
 * Bonsai is distributed in the hope that it will be useful,                    *
 * but WITHOUT ANY WARRANTY; without even the implied warranty of               *
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the                 *
 * GNU General Public License for more details.                                 *
 *                                                                              *
 * You should have received a copy of the GNU General Public License            *
 * along with this program. If not, see <http://www.gnu.org/licenses/>.         *
 *                                                                              *
 ********************************************************************************/

#include "MessageBox.h"

namespace bonsaiviewer::components::message_box {

namespace {

QMessageBox::StandardButton show(QMessageBox::Icon icon,
                                 QWidget* parent,
                                 const QString& title,
                                 const QString& text,
                                 QMessageBox::StandardButtons buttons,
                                 QMessageBox::StandardButton default_button) {
    QMessageBox box(icon, title, QString(), buttons, parent);
    box.setTextFormat(Qt::PlainText);
    box.setText(text);
    box.setDefaultButton(default_button);
    if (box.exec() == -1) {
        return QMessageBox::Cancel;
    }
    return box.standardButton(box.clickedButton());
}

} // namespace

QMessageBox::StandardButton information(QWidget* parent,
                                        const QString& title,
                                        const QString& text,
                                        QMessageBox::StandardButtons buttons,
                                        QMessageBox::StandardButton default_button) {
    return show(QMessageBox::Information, parent, title, text, buttons, default_button);
}

QMessageBox::StandardButton question(QWidget* parent,
                                     const QString& title,
                                     const QString& text,
                                     QMessageBox::StandardButtons buttons,
                                     QMessageBox::StandardButton default_button) {
    return show(QMessageBox::Question, parent, title, text, buttons, default_button);
}

QMessageBox::StandardButton warning(QWidget* parent,
                                    const QString& title,
                                    const QString& text,
                                    QMessageBox::StandardButtons buttons,
                                    QMessageBox::StandardButton default_button) {
    return show(QMessageBox::Warning, parent, title, text, buttons, default_button);
}

} // namespace bonsaiviewer::components::message_box
