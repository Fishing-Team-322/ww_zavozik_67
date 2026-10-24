"""Portable process peak working-set reporting for offline experiments."""
import sys


def peak_rss_mib():
    if sys.platform == "win32":
        import psutil  # included in the isolated Windows benchmark environment
        return psutil.Process().memory_info().peak_wset / 2**20
    import resource
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / (2**20 if sys.platform == "darwin" else 1024)
