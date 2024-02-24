import datetime
import json
import locale
import pathlib

import click
import cron_descriptor
from ruamel.yaml import YAML

from commands import gyrobot
from commands.extended_context import ExtendedContext
from commands.openshift.api import KubernetesConnection
from commands.openshift.common import read_config, OpenShiftNamespace, check_security

yaml = YAML()
REMOVE_CRONJOB_KEYS = ['Containers', 'Images', 'Selector']
_cronjob_config = read_config('OPENSHIFT_CRONJOB')
_data_file = pathlib.Path('data') / 'cronjob-stack.yml'
if not _data_file.exists():
    _data_file.write_text('')


def _new_get_month_description(self):
    """Generates a description for only the MONTH portion of the expression

    Returns:
        The MONTH description

    """
    month_names_accusative = {
        'Ιανουάριος': 'ν Ιανουάριο',
        'Φεβρουάριος': ' Φεβρουάριο',
        'Μάρτιος': ' Μάρτιο',
        'Απρίλιος': 'ν Απρίλιο',
        'Μάιος': ' Μάιο',
        'Ιούνιος': 'ν Ιούνιο',
        'Ιούλιος': 'ν Ιούλιο',
        'Αύγουστος': 'ν Αύγουστο',
        'Σεπτέμβριος': ' Σεπτέμβριο',
        'Οκτώβριος': 'ν Οκτώβριο',
        'Νοέμβριος': ' Νοέμβριο',
        'Δεκέμβριος': ' Δεκέμβριο',
        'Ιανουαρίου': 'ν Ιανουάριο',
        'Φεβρουαρίου': ' Φεβρουάριο',
        'Μαρτίου': ' Μάρτιο',
        'Απριλίου': 'ν Απρίλιο',
        'Μαΐου': ' Μάιο',
        'Ιουνίου': 'ν Ιούνιο',
        'Ιουλίου': 'ν Ιούλιο',
        'Αυγούστου': 'ν Αύγουστο',
        'Σεπτεμβρίου': ' Σεπτέμβριο',
        'Οκτωβρίου': 'ν Οκτώβριο',
        'Νοεμβρίου': ' Νοέμβριο',
        'Δεκεμβρίου': ' Δεκέμβριο'
    }
    if locale.getlocale()[0] in ['el_GR', 'Greek_Greece']:
        extras = lambda x: month_names_accusative.get(x, x)
    else:
        extras = lambda x: x
    return self.get_segment_description(
        self._expression_parts[4],
        '',
        lambda s: extras(datetime.date(datetime.date.today().year, int(s), 1).strftime("%B")),
        lambda s: self._(", every {0} months").format(s),
        lambda s: self._(", month {0} through month {1}") or self._(", {0} through {1}"),
        lambda s: self._(", only in {0}"),
        lambda s: self._(", month {0} through month {1}") or self._(", {0} through {1}")
    )


def _cron_descriptor_options():
    cron_descriptor_options = cron_descriptor.Options()
    cron_descriptor_options.casing_type = cron_descriptor.CasingTypeEnum.Sentence
    if locale.getlocale()[0] in ['el_GR', 'Greek_Greece']:
        cron_descriptor_options.locale_code = 'el_GR'
        cron_descriptor_options.locale_location = 'locale/cron_descriptor'
    cron_descriptor_options.use_24hour_time_format = True
    return cron_descriptor_options


cron_descriptor.ExpressionDescriptor.get_month_description = _new_get_month_description


def _schedule_description(schedule: str) -> str:
    cron_descriptor_options = _cron_descriptor_options()
    return cron_descriptor.ExpressionDescriptor(schedule, cron_descriptor_options).get_description(
        cron_descriptor.DescriptionTypeEnum.FULL)


@gyrobot.group('cronjob')
@click.pass_context
def cronjob(ctx: ExtendedContext):
    ctx.ensure_object(dict)
    ctx.obj['config'] = _cronjob_config
    ctx.obj['security_text'] = {'list': 'list cronjobs', 'pause': 'pause cronjobs', 'resume': 'resume cronjobs'}


@cronjob.command('list')
@click.argument('namespace', type=OpenShiftNamespace(_cronjob_config))
@click.option('-x', '--excel', is_flag=True, default=False)
@click.pass_context
@check_security
def list_cronjobs(ctx: ExtendedContext, namespace: str, excel: bool):
    with KubernetesConnection(ctx, namespace) as conn:
        cronjobs = conn.batch_v1_api.list_namespaced_cron_job(namespace)

    cronjob_table = [{
        'Name': r.metadata.name,
        'Suspended': r.spec.suspend,
        'Last Schedule Time': r.status.last_schedule_time,
        'Last Successful Tiome': r.status.last_successful_time,
        'Schedule': _schedule_description(r.spec.schedule),
        'Schedule Raw': r.spec.schedule}
        for r in cronjobs.items]
    ctx.chat.send_table(title='cronjobs', table=cronjob_table, send_as_excel=excel)


@cronjob.command('pause')
@click.argument('namespace', type=OpenShiftNamespace(_cronjob_config))
@click.option('-x', '--excel', is_flag=True, default=False)
@click.pass_context
@check_security
def pause_cronjob(ctx: ExtendedContext, namespace: str, excel: bool):
    with open('data/cronjob-stack.yml', mode='r', encoding='utf8') as f:
        suspended_cronjobs_stack = yaml.load(f) or []
    with KubernetesConnection(ctx, namespace) as conn:
        cronjobs = conn.batch_v1_api.list_namespaced_cron_job(namespace)
        suspended_cronjobs = []
        result = []
        for r in cronjobs.items:
            if r.spec.suspend:
                continue
            suspended_cronjobs.append(r.metadata.name)
            result.append(
                conn.batch_v1_api.patch_namespaced_cron_job(
                    r.metadata.name,
                    namespace,
                    {'spec': {'suspend': True}}))
    suspended_cronjobs_stack.append(suspended_cronjobs)
    with open('data/cronjob-stack.yml', mode='w', encoding='utf8') as f:
        yaml.dump(suspended_cronjobs_stack, f)
    cronjob_table = [{
        'Name': r.metadata.name,
        'Suspended': r.spec.suspend,
        'Last Schedule Time': r.status.last_schedule_time,
        'Last Successful Tiome': r.status.last_successful_time,
        'Schedule': _schedule_description(r.spec.schedule),
        'Schedule Raw': r.spec.schedule}
        for r in result]
    ctx.chat.send_table(title='cronjobs', table=cronjob_table, send_as_excel=excel)


@cronjob.command('resume')
@click.argument('namespace', type=OpenShiftNamespace(_cronjob_config))
@click.option('-x', '--excel', is_flag=True, default=False)
@click.pass_context
@check_security
def resume_cronjob(ctx: ExtendedContext, namespace, excel: bool):
    with open('data/cronjob-stack.yml', mode='r', encoding='utf8') as f:
        suspended_cronjobs_stack = yaml.load(f) or []
    if len(suspended_cronjobs_stack) == 0:
        ctx.chat.send_text("No cronjobs to resume", is_error=True)
        return
    cronjobs_to_resume = suspended_cronjobs_stack.pop() or []
    result = []
    with KubernetesConnection(ctx, namespace) as conn:
        for one_cronjob_name in cronjobs_to_resume:
            result.append(
                conn.batch_v1_api.patch_namespaced_cron_job(
                    one_cronjob_name,
                    namespace,
                    {'spec': {'suspend': False}}))
    with open('data/cronjob-stack.yml', mode='w', encoding='utf8') as f:
        yaml.dump(suspended_cronjobs_stack, f)
    cronjob_table = [{
        'Name': r.metadata.name,
        'Suspended': r.spec.suspend,
        'Last Schedule Time': r.status.last_schedule_time,
        'Last Successful Tiome': r.status.last_successful_time,
        'Schedule': _schedule_description(r.spec.schedule),
        'Schedule Raw': r.spec.schedule}
        for r in result]
    ctx.chat.send_table(title='cronjobs', table=cronjob_table, send_as_excel=excel)
