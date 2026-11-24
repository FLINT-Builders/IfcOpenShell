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

// Model strings must reach the properties panel as plain text. An <img> whose
// source is a file URL must not cause Qt to open that path: on Windows,
// file://host/share/... is a UNC path and opening it starts an SMB session.
//
// The assertions follow PropertiesPanelView::refresh (View.cpp): scalar
// attributes, the type and container names, predefined type, and property and
// quantity sets are copied unchanged into PropertiesPanel::render. The sidecar
// fallback (class + Name) uses the same labels; its string-table decode is not
// executed here because ElementRegistry::onSidecarElementsReady is private.
//
// Not covered, same class of sink, different widgets:
//   * MainWindow status QLabel (MainWindow.cpp setText of the status detail),
//     including "Viewing " + a federation display_name.
//   * SettingsDialog read-only QLabels for a conversion-based unit name.

#include "modules/properties/Panel.h"
#include "modules/properties/Types.h"

#include "element.h"
#include "pset.h"

#include <ifcparse/file.h>

#include <QtCore/private/qabstractfileengine_p.h>
#include <QApplication>
#include <QLabel>
#include <QTest>

#include <sstream>
#include <string>

namespace {

const QString kProbeHost = QStringLiteral("richtext-probe.example");
const QString kProbeDir = QStringLiteral("/tmp/bonsai-richtext-probe");

QString localImage(const QString& leaf) {
    return QStringLiteral("<img src=\"file://%1/%2\">").arg(kProbeDir, leaf);
}

QString hostImage(const QString& leaf) {
    return QStringLiteral("<img src=\"file://%1/share/%2\">").arg(kProbeHost, leaf);
}

// Records every QFile / QFileInfo engine request whose path carries a probe
// token. Returning nullptr lets Qt's own engine continue, so a hit means the
// product asked Qt to open that path.
class ProbeFileEngineHandler : public QAbstractFileEngineHandler {
public:
    mutable QStringList paths;

    std::unique_ptr<QAbstractFileEngine> create(const QString& fileName) const override {
        if (fileName.contains(kProbeDir) || fileName.contains(kProbeHost)) {
            paths.append(fileName);
        }
        return nullptr;
    }
};

QString spfQuoted(const QString& text) {
    return QString(text).replace(QLatin1Char('\''), QLatin1String("''"));
}

QString buildProbeFile() {
    const auto q = [](const QString& text) { return "'" + spfQuoted(text) + "'"; };
    const QString name = localImage(QStringLiteral("name.png"));
    const QString description = localImage(QStringLiteral("description.png"));
    const QString type_name = localImage(QStringLiteral("type-name.png"));
    const QString element_type = hostImage(QStringLiteral("predefined.png"));
    const QString container = localImage(QStringLiteral("container.png"));
    const QString property_name = localImage(QStringLiteral("property-name.png"));
    const QString property_value = hostImage(QStringLiteral("property-value.png"));
    const QString quantity_name = localImage(QStringLiteral("quantity-name.png"));

    return QStringLiteral(
               "ISO-10303-21;\n"
               "HEADER;\n"
               "FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');\n"
               "FILE_NAME('','1970-01-01T00:00:00',(''),(''),'','','');\n"
               "FILE_SCHEMA(('IFC4'));\n"
               "ENDSEC;\n"
               "DATA;\n"
               "#1=IFCWALL('1aaaaaaaaaaaaaaaaaaaaa',$,%1,%2,$,$,$,$,$);\n"
               "#2=IFCWALLTYPE('2aaaaaaaaaaaaaaaaaaaaa',$,%3,$,$,$,$,$,%4,.USERDEFINED.);\n"
               "#3=IFCBUILDINGSTOREY('3aaaaaaaaaaaaaaaaaaaaa',$,%5,$,$,$,$,$,$,$);\n"
               "#4=IFCRELDEFINESBYTYPE('4aaaaaaaaaaaaaaaaaaaaa',$,$,$,(#1),#2);\n"
               "#5=IFCRELCONTAINEDINSPATIALSTRUCTURE('5aaaaaaaaaaaaaaaaaaaaa',$,$,$,(#1),#3);\n"
               "#6=IFCPROPERTYSINGLEVALUE(%6,$,IFCLABEL(%7),$);\n"
               "#7=IFCPROPERTYSET('7aaaaaaaaaaaaaaaaaaaaa',$,'PsetProbe',$,(#6));\n"
               "#8=IFCRELDEFINESBYPROPERTIES('8aaaaaaaaaaaaaaaaaaaaa',$,$,$,(#1),#7);\n"
               "#9=IFCQUANTITYLENGTH(%8,$,$,1.,$);\n"
               "#10=IFCELEMENTQUANTITY('0aaaaaaaaaaaaaaaaaaaaa',$,'QtoProbe',$,$,(#9));\n"
               "#11=IFCRELDEFINESBYPROPERTIES('baaaaaaaaaaaaaaaaaaaaa',$,$,$,(#1),#10);\n"
               "ENDSEC;\n"
               "END-ISO-10303-21;\n")
        .arg(q(name), q(description), q(type_name), q(element_type), q(container), q(property_name),
             q(property_value), q(quantity_name));
}

std::optional<QString> formatPropertyValue(const property_value& value) {
    if (const auto* text = value.get_if<std::string>()) {
        return QString::fromStdString(*text);
    }
    if (const auto* flag = value.get_if<bool>()) {
        return *flag ? QStringLiteral("True") : QStringLiteral("False");
    }
    if (const auto* integer = value.get_if<std::int64_t>()) {
        return QString::number(static_cast<qlonglong>(*integer));
    }
    if (const auto* real = value.get_if<double>()) {
        return QString::number(*real);
    }
    return std::nullopt;
}

QList<bonsaiviewer::modules::properties::PropertySet> toPropertySets(const element_properties& sets) {
    QList<bonsaiviewer::modules::properties::PropertySet> result;
    for (const auto& [set_name, properties] : sets) {
        bonsaiviewer::modules::properties::PropertySet set;
        set.title = QString::fromStdString(set_name);
        for (const auto& [property_name, value] : properties) {
            if (property_name == "id") {
                continue;
            }
            if (auto formatted = formatPropertyValue(value)) {
                set.rows.append({QString::fromStdString(property_name), *formatted});
            }
        }
        if (!set.rows.isEmpty()) {
            result.append(set);
        }
    }
    return result;
}

// Same copies as PropertiesPanelView::refresh once an entity has been resolved.
bonsaiviewer::modules::properties::PropertiesPanelState stateFromEntity(const express::base& entity) {
    bonsaiviewer::modules::properties::PropertiesPanelState state;
    state.entity.entity_class = QString::fromStdString(entity.declaration().name());
    if (auto predefined_type = get_predefined_type(entity)) {
        state.entity.predefined_type = QString::fromStdString(*predefined_type);
    }
    for (const auto& [name, value] : get_scalar_attributes(entity)) {
        state.attributes.append({QString::fromStdString(name), QString::fromStdString(value)});
    }
    auto display_name = [](const express::base& related) -> QString {
        if (auto name = get_string_attribute(related, "Name"); name && !name->empty()) {
            return QString::fromStdString(*name);
        }
        return QString::fromStdString(related.declaration().name());
    };
    if (express::base type = get_type(entity)) {
        state.relationships.append({QStringLiteral("Type"), display_name(type)});
    }
    if (express::base container = get_container(entity)) {
        state.relationships.append({QStringLiteral("Container"), display_name(container)});
    }
    state.property_sets = toPropertySets(get_psets(entity, /*psets_only=*/true, /*qtos_only=*/false));
    state.quantity_sets = toPropertySets(get_psets(entity, /*psets_only=*/false, /*qtos_only=*/true));
    return state;
}

express::base loadWall() {
    const QByteArray bytes = buildProbeFile().toUtf8();
    std::istringstream stream(std::string(bytes.constData(), static_cast<std::size_t>(bytes.size())));
    // The file owns the instances. Leak it for the process lifetime so the
    // returned entity stays valid; this test process exits immediately after.
    auto* kept = new ifcopenshell::file(stream, static_cast<int>(bytes.size()));
    if (!kept->good()) {
        throw std::runtime_error("probe IFC did not parse");
    }
    const auto walls = kept->instances_by_type("IfcWall");
    if (walls.size() != 1) {
        throw std::runtime_error("probe IFC did not contain one IfcWall");
    }
    return walls.front();
}

template <typename Row>
bool rowEquals(const QList<Row>& rows, const QString& key, const QString& value) {
    for (const auto& row : rows) {
        if (row.key == key && row.value == value) {
            return true;
        }
    }
    return false;
}

bool setHasRow(const QList<bonsaiviewer::modules::properties::PropertySet>& sets, const QString& title,
               const QString& key, const QString& value) {
    for (const auto& set : sets) {
        if (set.title == title && rowEquals(set.rows, key, value)) {
            return true;
        }
    }
    return false;
}

void realize(QWidget* root) {
    root->show();
    root->adjustSize();
    const auto labels = root->findChildren<QLabel*>();
    for (QLabel* label : labels) {
        label->sizeHint();
        label->grab();
    }
    QApplication::processEvents();
}

QString labelDump(QWidget* root) {
    QString text;
    const auto labels = root->findChildren<QLabel*>();
    for (QLabel* label : labels) {
        text += QStringLiteral("label object=%1 format=%2 text=%3\n")
                    .arg(label->objectName())
                    .arg(static_cast<int>(label->textFormat()))
                    .arg(label->text());
    }
    return text;
}

} // namespace

class PropertiesRichTextTest : public QObject {
    Q_OBJECT
private slots:
    void init();
    void ifcModelTextDoesNotOpenImagePaths();
    void entityClassAndSidecarNameDoNotOpenImagePaths();
    void plainAttributeDoesNotOpenImagePaths();

private:
    ProbeFileEngineHandler handler_;
};

void PropertiesRichTextTest::init() {
    handler_.paths.clear();
}

void PropertiesRichTextTest::ifcModelTextDoesNotOpenImagePaths() {
    express::base wall;
    try {
        wall = loadWall();
    } catch (const std::exception& ex) {
        QFAIL(ex.what());
    }
    const auto state = stateFromEntity(wall);

    QVERIFY2(rowEquals(state.attributes, QStringLiteral("Name"), localImage(QStringLiteral("name.png"))),
             "Name did not arrive unchanged from the IFC file");
    QVERIFY2(rowEquals(state.attributes, QStringLiteral("Description"), localImage(QStringLiteral("description.png"))),
             "Description did not arrive unchanged from the IFC file");
    QCOMPARE(state.entity.predefined_type, hostImage(QStringLiteral("predefined.png")));
    QVERIFY2(rowEquals(state.relationships, QStringLiteral("Type"), localImage(QStringLiteral("type-name.png"))),
             "type name did not arrive unchanged");
    QVERIFY2(rowEquals(state.relationships, QStringLiteral("Container"), localImage(QStringLiteral("container.png"))),
             "container name did not arrive unchanged");
    QVERIFY2(setHasRow(state.property_sets, QStringLiteral("PsetProbe"),
                       localImage(QStringLiteral("property-name.png")),
                       hostImage(QStringLiteral("property-value.png"))),
             "property name or value did not arrive unchanged");
    QVERIFY2(setHasRow(state.quantity_sets, QStringLiteral("QtoProbe"), localImage(QStringLiteral("quantity-name.png")),
                       QStringLiteral("1")),
             "quantity name did not arrive unchanged");

    bonsaiviewer::modules::properties::PropertiesPanel panel;
    panel.render(state);
    realize(&panel);

    QStringList opened = handler_.paths;
    opened.removeDuplicates();
    const QString detail = labelDump(&panel) + QStringLiteral("opened:\n") + opened.join(QLatin1Char('\n'));
    QVERIFY2(handler_.paths.isEmpty(), qPrintable(detail));
}

void PropertiesRichTextTest::entityClassAndSidecarNameDoNotOpenImagePaths() {
    // PropertiesPanelView::refresh writes these two strings into the entity
    // class label and the Name row when only sidecar basic info is available.
    bonsaiviewer::modules::properties::PropertiesPanelState state;
    state.entity.entity_class = localImage(QStringLiteral("entity-class.png"));
    state.entity.predefined_type = QStringLiteral("N/A");
    state.attributes.append({QStringLiteral("Name"), hostImage(QStringLiteral("sidecar-name.png"))});
    state.attributes.append({QStringLiteral("GlobalId"), QStringLiteral("1aaaaaaaaaaaaaaaaaaaaa")});

    bonsaiviewer::modules::properties::PropertiesPanel panel;
    panel.render(state);
    realize(&panel);

    QStringList opened = handler_.paths;
    opened.removeDuplicates();
    const QString detail = labelDump(&panel) + QStringLiteral("opened:\n") + opened.join(QLatin1Char('\n'));
    QVERIFY2(handler_.paths.isEmpty(), qPrintable(detail));
}

void PropertiesRichTextTest::plainAttributeDoesNotOpenImagePaths() {
    bonsaiviewer::modules::properties::PropertiesPanelState state;
    state.entity.entity_class = QStringLiteral("IfcWall");
    state.entity.predefined_type = QStringLiteral("SOLIDWALL");
    state.attributes.append({QStringLiteral("Name"), QStringLiteral("Wall-1")});

    bonsaiviewer::modules::properties::PropertiesPanel panel;
    panel.render(state);
    realize(&panel);

    QVERIFY(handler_.paths.isEmpty());
    bool saw_name = false;
    const auto labels = panel.findChildren<QLabel*>();
    for (QLabel* label : labels) {
        if (label->text() == QStringLiteral("Wall-1")) {
            saw_name = true;
        }
    }
    QVERIFY(saw_name);
}

int main(int argc, char** argv) {
    qputenv("QT_QPA_PLATFORM", QByteArray("offscreen"));
    QApplication app(argc, argv);
    PropertiesRichTextTest test;
    return QTest::qExec(&test, argc, argv);
}

#include "test_properties_richtext.moc"
