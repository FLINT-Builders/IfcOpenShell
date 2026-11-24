/* This file was generated with the assistance of an AI coding tool. */
/*
 * Interposes the libc calls Qt uses for QFileInfo::exists and QFile::open.
 * Paths are appended to $FEDERATION_PROBE_LOG. Symbol lookup is finished in
 * a constructor so a hook never calls dlsym.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

static __thread int in_hook;

static int (*real_stat)(const char*, struct stat*);
static int (*real_lstat)(const char*, struct stat*);
static int (*real_stat64)(const char*, struct stat64*);
static int (*real_lstat64)(const char*, struct stat64*);
static int (*real_statx)(int, const char*, int, unsigned int, struct statx*);
static int (*real_open)(const char*, int, ...);
static int (*real_open64)(const char*, int, ...);
static int (*real_openat)(int, const char*, int, ...);
static int (*real_openat64)(int, const char*, int, ...);
static FILE* (*real_fopen)(const char*, const char*);
static int (*real_access)(const char*, int);
static int (*real_faccessat)(int, const char*, int, int);

static void init_probe(void) __attribute__((constructor));
static void init_probe(void) {
    in_hook = 1;
    real_stat = dlsym(RTLD_NEXT, "stat");
    real_lstat = dlsym(RTLD_NEXT, "lstat");
    real_stat64 = dlsym(RTLD_NEXT, "stat64");
    real_lstat64 = dlsym(RTLD_NEXT, "lstat64");
    real_statx = dlsym(RTLD_NEXT, "statx");
    real_open = dlsym(RTLD_NEXT, "open");
    real_open64 = dlsym(RTLD_NEXT, "open64");
    real_openat = dlsym(RTLD_NEXT, "openat");
    real_openat64 = dlsym(RTLD_NEXT, "openat64");
    real_fopen = dlsym(RTLD_NEXT, "fopen");
    real_access = dlsym(RTLD_NEXT, "access");
    real_faccessat = dlsym(RTLD_NEXT, "faccessat");
    in_hook = 0;
}

static void log_path(const char* path) {
    const char* log;
    int fd;
    if (in_hook || path == NULL || path[0] == '\0' || real_open == NULL) return;
    log = getenv("FEDERATION_PROBE_LOG");
    if (log == NULL || log[0] == '\0') return;
    in_hook = 1;
    fd = real_open(log, O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (fd >= 0) {
        size_t len = strlen(path);
        ssize_t w = write(fd, path, len);
        (void)w;
        w = write(fd, "\n", 1);
        (void)w;
        close(fd);
    }
    in_hook = 0;
}

int stat(const char* path, struct stat* buf) {
    log_path(path);
    return real_stat(path, buf);
}

int lstat(const char* path, struct stat* buf) {
    log_path(path);
    return real_lstat(path, buf);
}

int stat64(const char* path, struct stat64* buf) {
    log_path(path);
    if (!real_stat64) {
        errno = ENOSYS;
        return -1;
    }
    return real_stat64(path, buf);
}

int lstat64(const char* path, struct stat64* buf) {
    log_path(path);
    if (!real_lstat64) {
        errno = ENOSYS;
        return -1;
    }
    return real_lstat64(path, buf);
}

int statx(int dirfd, const char* pathname, int flags, unsigned int mask, struct statx* statxbuf) {
    log_path(pathname);
    if (!real_statx) {
        errno = ENOSYS;
        return -1;
    }
    return real_statx(dirfd, pathname, flags, mask, statxbuf);
}

int open(const char* path, int flags, ...) {
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list ap;
        va_start(ap, flags);
        mode = (mode_t)va_arg(ap, int);
        va_end(ap);
    }
    log_path(path);
    if (!real_open) return (int)syscall(SYS_open, path, flags, mode);
    return real_open(path, flags, mode);
}

int open64(const char* path, int flags, ...) {
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list ap;
        va_start(ap, flags);
        mode = (mode_t)va_arg(ap, int);
        va_end(ap);
    }
    log_path(path);
    if (real_open64) return real_open64(path, flags, mode);
    if (real_open) return real_open(path, flags, mode);
    return (int)syscall(SYS_open, path, flags, mode);
}

int openat(int dirfd, const char* path, int flags, ...) {
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list ap;
        va_start(ap, flags);
        mode = (mode_t)va_arg(ap, int);
        va_end(ap);
    }
    log_path(path);
    if (!real_openat) return (int)syscall(SYS_openat, dirfd, path, flags, mode);
    return real_openat(dirfd, path, flags, mode);
}

int openat64(int dirfd, const char* path, int flags, ...) {
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list ap;
        va_start(ap, flags);
        mode = (mode_t)va_arg(ap, int);
        va_end(ap);
    }
    log_path(path);
    if (real_openat64) return real_openat64(dirfd, path, flags, mode);
    if (real_openat) return real_openat(dirfd, path, flags, mode);
    return (int)syscall(SYS_openat, dirfd, path, flags, mode);
}

FILE* fopen(const char* path, const char* mode) {
    log_path(path);
    return real_fopen(path, mode);
}

int access(const char* path, int mode) {
    log_path(path);
    return real_access(path, mode);
}

int faccessat(int dirfd, const char* path, int mode, int flags) {
    log_path(path);
    return real_faccessat(dirfd, path, mode, flags);
}
