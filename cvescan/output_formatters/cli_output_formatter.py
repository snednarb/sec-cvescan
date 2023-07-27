from sys import stdout
from textwrap import wrap
from typing import List

from tabulate import tabulate

import cvescan.constants as const
import cvescan.target_sysinfo as TargetSysInfo
from cvescan.output_formatters import (
    AbstractOutputFormatter,
    AbstractStackableScanResultSorter,
    ScanStats,
)
from cvescan.scan_result import ScanResult


class CLIOutputFormatter(AbstractOutputFormatter):
    NOT_APPLICABLE = "N/A"
    DISABLED = "(disabled)"

    # TODO: These colors don't all show clearly on a light background
    priority_to_color_code = {
        const.UNTRIAGED: 5,
        const.NEGLIGIBLE: 193,
        const.LOW: 228,
        const.MEDIUM: 3,
        const.HIGH: 208,
        const.CRITICAL: 1,
    }

    def __init__(self, opt, logger, sorter: AbstractStackableScanResultSorter = None):
        super().__init__(opt, logger, sorter)

    def format_output(
        self, scan_results: List[ScanResult], sysinfo: TargetSysInfo
    ) -> (str, int):
        scan_results = self._filter_on_experimental(scan_results)

        priority_results = self._filter_on_priority(scan_results)
        fixable_results = self._filter_on_fixable(priority_results)

        stats = self._get_scan_stats(scan_results, sysinfo)

        msg = ""
        table_msg = self._format_table(priority_results, fixable_results, sysinfo)

        if table_msg:
            msg += "%s\n\n" % table_msg

        summary_msg = self._format_summary(stats, sysinfo)
        msg += summary_msg

        suggestions_msg = self._format_suggestions(stats, sysinfo)
        if suggestions_msg:
            msg += "\n\n%s" % suggestions_msg

        return_code = CLIOutputFormatter._determine_return_code(
            priority_results, fixable_results
        )

        return (msg, return_code)

    def _format_summary(self, stats: ScanStats, sysinfo: TargetSysInfo):
        # Disabling for now
        # apps_enabled =
        # CLIOutputFormatter._format_esm_enabled(sysinfo.esm_apps_enabled)
        # infra_enabled = CLIOutputFormatter._format_esm_enabled(
        # sysinfo.esm_infra_enabled
        # )

        # TODO: This is a hack. See issue #42
        if sysinfo.esm_apps_enabled is None or sysinfo.esm_infra_enabled is None:
            ua_archive_enabled = None
        else:
            ua_archive_enabled = True

        fixable_vulns = CLIOutputFormatter._colorize_fixes(
            stats.fixable_vulns, ua_archive_enabled
        )
        apps_vulns = CLIOutputFormatter._colorize_fixes(
            stats.apps_vulns, sysinfo.esm_apps_enabled
        )
        infra_vulns = CLIOutputFormatter._colorize_fixes(
            stats.infra_vulns, sysinfo.esm_infra_enabled
        )
        upgrade_vulns = CLIOutputFormatter._colorize_fixes(
            stats.upgrade_vulns, ua_archive_enabled
        )
        missing_fixes = CLIOutputFormatter._colorize_esm_combined_fixes(
            stats.missing_fixes, sysinfo
        )

        summary = list()
        summary.append(["Ubuntu Release", sysinfo.codename])
        summary.append(["Installed Packages", stats.installed_pkgs])
        summary.append(["CVE Priority", self._format_summary_priority()])
        summary.append(["Unique Packages Fixable by Patching", stats.fixable_packages])
        summary.append(["Unique CVEs Fixable by Patching", stats.fixable_cves])
        summary.append(["Vulnerabilities Fixable by Patching", fixable_vulns])
        if self.opt.experimental_mode:
            summary.append([f"Vulnerabilities Fixable by {const.UA_APPS}", apps_vulns])
            summary.append(
                [f"Vulnerabilities Fixable by {const.UA_INFRA}", infra_vulns]
            )
            # Disabling for now
            # summary.append(["UA Apps Enabled", apps_enabled])
            # summary.append(["UA Infra Enabled", infra_enabled])
        summary.append(["Fixes Available by `apt-get upgrade`", upgrade_vulns])
        if self.opt.experimental_mode:
            summary.append(
                ["Available Fixes Not Applied by `apt-get upgrade`", missing_fixes]
            )
        return "Summary\n" + tabulate(summary)

    def _format_summary_priority(self):
        if self.opt.priority == const.ALL:
            return "All"

        return "%s or higher" % self.opt.priority

    #   Disable for now
    #   @classmethod
    #   def _format_esm_enabled(cls, enabled):
    #       if enabled is None:
    #           return cls._colorize(const.REPOSITORY_UNKNOWN_COLOR_CODE, "Unknown")

    #       if enabled is True:
    #           return cls._colorize(const.REPOSITORY_ENABLED_COLOR_CODE, "Yes")

    #       return cls._colorize(const.REPOSITORY_DISABLED_COLOR_CODE, "No")

    def _format_table(self, priority_results, fixable_results, sysinfo):
        if self.opt.unresolved:
            self.sort(priority_results)
            results = priority_results
        else:
            self.sort(fixable_results)
            results = fixable_results

        if len(results) == 0:
            return ""

        formatted_results = self._transform_results(results, sysinfo)

        headers = ["CVE ID", "PRIORITY", "PACKAGE", "FIXED VERSION", "REPOSITORY"]
        if self.opt.show_links:
            headers.append("URL")

        return tabulate(formatted_results, headers, tablefmt="plain")

    def _clean_priority(self, p):
        return p[0] if isinstance(p, list) else p;

    def _transform_results(self, scan_results, sysinfo):
        for sr in scan_results:
            fixed_version = sr.fixed_version if sr.fixed_version else "Unresolved"
            priority = CLIOutputFormatter._colorize_priority(self._clean_priority(sr.priority))
            repository = self._transform_repository(sr.repository, sysinfo)

            result = [sr.cve_id, priority, sr.package_name, fixed_version, repository]
            if self.opt.show_links:
                uct_link = const.UCT_URL % sr.cve_id
                result.append(uct_link)

            yield result

    @classmethod
    def _colorize_priority(cls, priority):
        priority_color_code = cls.priority_to_color_code[priority]
        return cls._colorize(priority_color_code, priority)

    def _colorize_repository(self, repository, sysinfo):
        if (
            not repository
            or sysinfo.esm_apps_enabled is None
            or sysinfo.esm_infra_enabled is None
        ):
            return repository

        if const.UBUNTU_ARCHIVE in repository:
            color_code = const.REPOSITORY_ENABLED_COLOR_CODE
        elif const.UA_APPS in repository:
            color_code = CLIOutputFormatter._get_ua_repository_color_code(
                sysinfo.esm_apps_enabled
            )
        elif const.UA_INFRA in repository:
            color_code = CLIOutputFormatter._get_ua_repository_color_code(
                sysinfo.esm_infra_enabled
            )
        else:
            self.logger.warning("Unknown repository %s" % repository)
            color_code = const.REPOSITORY_DISABLED_COLOR_CODE

        return CLIOutputFormatter._colorize(color_code, repository)

    @staticmethod
    def _get_ua_repository_color_code(enabled):
        if enabled:
            return const.REPOSITORY_ENABLED_COLOR_CODE
        else:
            return const.REPOSITORY_DISABLED_COLOR_CODE

    def _transform_repository(self, repository, sysinfo):
        if repository:
            if repository == const.UA_APPS:
                if sysinfo.esm_apps_enabled is False:
                    repository += " " + CLIOutputFormatter.DISABLED
            elif repository == const.UA_INFRA:
                if sysinfo.esm_infra_enabled is False:
                    repository += " " + CLIOutputFormatter.DISABLED

            return self._colorize_repository(repository, sysinfo)

        return CLIOutputFormatter.NOT_APPLICABLE

    @classmethod
    def _colorize_esm_combined_fixes(cls, fixes, sysinfo):
        if sysinfo.esm_apps_enabled is False or sysinfo.esm_infra_enabled is False:
            return cls._colorize_fixes(fixes, False)

        if sysinfo.esm_apps_enabled is None or sysinfo.esm_infra_enabled is None:
            return cls._colorize_fixes(fixes, None)

        return cls._colorize_fixes(fixes, True)

    @classmethod
    def _colorize_fixes(cls, fixes, enabled):
        if fixes == 0:
            return str(fixes)

        if enabled is None:
            return fixes

        if enabled:
            return cls._colorize(const.REPOSITORY_ENABLED_COLOR_CODE, fixes)

        return cls._colorize(const.REPOSITORY_DISABLED_COLOR_CODE, fixes)

    @staticmethod
    def _colorize(color_code, value):
        if not stdout.isatty():
            return str(value)

        return "\u001b[38;5;%dm%s\u001b[0m" % (color_code, str(value))

    def _format_suggestions(self, stats: ScanStats, sysinfo: TargetSysInfo):
        ua_msg = "%d additional security patch(es) are available if ESM for %s is enabled with Ubuntu Advantage. For more information, see %s."

        if stats.infra_vulns > 0 and sysinfo.esm_infra_enabled is False:
            infra_msg = ua_msg % (
                stats.infra_vulns,
                "Infrastructure",
                const.UA_INFRA_URL,
            )

            return CLIOutputFormatter._wrap_text(infra_msg)

        return ""

    @staticmethod
    def _wrap_text(text):
        return "\n".join(wrap(text, 88))
