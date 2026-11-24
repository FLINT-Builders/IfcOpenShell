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

#ifndef IFCINTERFACE_COMPONENTS_MESSAGEBOX_H
#define IFCINTERFACE_COMPONENTS_MESSAGEBOX_H

#include <QMessageBox>

// Replacements for the QMessageBox static helpers that always show the text as
// plain text. Use these whenever the text includes model, project or connector
// strings: the static helpers auto-detect rich text, so such a string could
// otherwise inject markup.
namespace bonsaiviewer::components::message_box {

QMessageBox::StandardButton information(QWidget* parent,
                                        const QString& title,
                                        const QString& text,
                                        QMessageBox::StandardButtons buttons = QMessageBox::Ok,
                                        QMessageBox::StandardButton default_button = QMessageBox::NoButton);

QMessageBox::StandardButton question(QWidget* parent,
                                     const QString& title,
                                     const QString& text,
                                     QMessageBox::StandardButtons buttons = QMessageBox::Yes | QMessageBox::No,
                                     QMessageBox::StandardButton default_button = QMessageBox::NoButton);

QMessageBox::StandardButton warning(QWidget* parent,
                                    const QString& title,
                                    const QString& text,
                                    QMessageBox::StandardButtons buttons = QMessageBox::Ok,
                                    QMessageBox::StandardButton default_button = QMessageBox::NoButton);

} // namespace bonsaiviewer::components::message_box

#endif
