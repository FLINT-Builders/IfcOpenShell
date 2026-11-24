// This file was generated with the assistance of an AI coding tool.
// Test stand-in for the Qt string API the measurement tools actually call.
// It does not parse, filter, or bounds-check triangle indices.
#ifndef MEAS_QT_H
#define MEAS_QT_H

#include <cstdarg>
#include <cstddef>
#include <cstdio>
#include <string>
#include <vector>

class QString {
public:
    QString() = default;
    QString(const char* s) : s_(s ? s : "") {}
    QString(const std::string& s) : s_(s) {}

    static QString number(double v, char fmt, int prec) {
        char buf[64];
        if (fmt == 'f') std::snprintf(buf, sizeof(buf), "%.*f", prec, v);
        else std::snprintf(buf, sizeof(buf), "%g", v);
        return QString(buf);
    }
    static QString fromLatin1(const char* s) { return QString(s); }

    // Replace the next %1..%9, in order. Enough for the measurement HUD.
    QString arg(const QString& a) const { return replaceNext(a.s_); }
    QString arg(const char* a) const { return replaceNext(a ? a : ""); }
    QString arg(size_t a) const { return replaceNext(std::to_string(a)); }
    QString arg(int a) const { return replaceNext(std::to_string(a)); }
    QString arg(double a, int /*fieldWidth*/, char fmt, int prec) const {
        return replaceNext(number(a, fmt, prec).s_);
    }

    std::string toStdString() const { return s_; }
    const std::string& str() const { return s_; }

    friend QString operator+(const QString& a, const QString& b) {
        return QString(a.s_ + b.s_);
    }
    friend QString operator+(const QString& a, const char* b) {
        return QString(a.s_ + (b ? b : ""));
    }
    friend QString operator+(const char* a, const QString& b) {
        return QString(std::string(a ? a : "") + b.s_);
    }

private:
    QString replaceNext(const std::string& rep) const {
        for (int n = 1; n <= 9; ++n) {
            const std::string tok = "%" + std::to_string(n);
            const auto pos = s_.find(tok);
            if (pos == std::string::npos) continue;
            return QString(s_.substr(0, pos) + rep + s_.substr(pos + tok.size()));
        }
        return *this;
    }
    std::string s_;
};

#define QStringLiteral(lit) QString(lit)

class QStringList : public std::vector<QString> {
public:
    QStringList& operator<<(const QString& s) {
        push_back(s);
        return *this;
    }
    QString join(char sep) const {
        std::string out;
        for (size_t i = 0; i < size(); ++i) {
            if (i) out.push_back(sep);
            out += (*this)[i].str();
        }
        return QString(out);
    }
};

template <class... Args>
void qInfo(const char*, Args...) {}

#endif
