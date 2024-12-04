import datetime
import json

import click

from commands import gyrobot
from commands.extended_context import ExtendedContext


@gyrobot.command('covid', aliases=['covid19', 'covid_19'],
                 context_settings={
                     'ignore_unknown_options': True,
                     'allow_extra_args': True})
@click.argument('country', type=click.STRING)
@click.pass_context
def covid(ctx: ExtendedContext, country: str):
    """Display last available statistics for COVID-19 cases

    Syntax:

    covid19 GR
    covid19 GRC
    covid19 Greece
    covid19 Ελλάδα"""

    def _lookup_country(a_country):
        a_country = a_country.lower()
        a_country = {'uk': 'gb'}.get(a_country, a_country)
        with open('countries.json') as f:
            country_lookup = json.load(f)
        # if a_country == 'usa': search_country = 'us'

        found_countries = [c for c in country_lookup
                           if a_country == c['name']['common'].lower()
                           or a_country == c['name']['official'].lower()
                           or any([a_country == names['common'].lower() for lang, names in c['name']['native'].items()])
                           or any(
                [a_country == names['official'].lower() for lang, names in c['name']['native'].items()])
                           or a_country == c['cca2'].lower()
                           or a_country == c['cca3'].lower()
                           or a_country == c['cioc'].lower()]
        result = found_countries[0] if len(found_countries) > 0 else None
        return result

    if country == '19' and len(ctx.args):
        country = ctx.args.pop(0)
    if len(ctx.args) > 0:
        country += ' ' + ' '.join(ctx.args)
    country_info = _lookup_country(country.lower())
    if not country_info:
        ctx.chat.send_text(f"Country \"{country}\" not found", is_error=True)
        return
    country = country_info['cca3'].upper()

    with open('data/owid-covid-data.json') as f:
        full_data = json.load(f)
        if isinstance(full_data, str):
            full_data = json.loads(full_data)
    country_data = full_data[country]
    data = {}
    relevant_data = list(filter(lambda d: ('new_cases' in d and 'new_deaths' in d), country_data['data']))
    for data_for_day in relevant_data[-7:-1]:
        data |= data_for_day
        if 'new_vaccinations' or 'total_vaccinations' in data_for_day:
            data['vaccinations_on'] = data_for_day['date']

    report_date = datetime.datetime.strptime(data['date'], '%Y-%m-%d')

    new_cases = data.get('new_cases', 0.0)
    new_deaths = data.get('new_deaths', 0.0)
    new_vaccinations = data.get('new_vaccinations', 0.0)
    total_vaccinations = data.get('total_vaccinations', 0.0)
    vaccinations_percent = data.get('total_vaccinations_per_hundred', 0.0)
    vaccinations_on = datetime.datetime.strptime(data['vaccinations_on'], '%Y-%m-%d')
    ctx.chat.send_text((f"*Date*: {report_date:%h %d %Y}\n"
                        f"*New Cases*: {new_cases:.10n}\n"
                        f"*Deaths*: {new_deaths:.10n}\n"
                        f"*Vaccinations*: {new_vaccinations:.10n}/{total_vaccinations:.10n} "
                        f"({vaccinations_percent:.5n}%) - on {vaccinations_on:%h %d %Y}"))
