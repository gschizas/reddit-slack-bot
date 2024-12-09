import io
import json
import os
import pathlib
import tempfile

import click
import psycopg
import xlsxwriter
from tabulate import tabulate

from bot_framework.yaml_wrapper import yaml
from commands import gyrobot
from commands.extended_context import ExtendedContext

if 'QUESTIONNAIRE_DATABASE_URL' not in os.environ:
    raise ImportError('QUESTIONNAIRE_DATABASE_URL not found in environment')

SQL_SURVEY_PREFILLED_ANSWERS = r"""select answer[3] AS Code, answer_value as Answer, count(*) AS VoteCount
from (select regexp_split_to_array(code, '_') AS answer_parts, *
      from "Answers"
      where  code = 'q_{0}' or code like 'q\_{0}\_%') AS dt(answer)
group by 1, 2
order by 3 desc"""
SQL_SURVEY_TEXT = r"""select answer_value as Answer, count(*) AS VoteCount 
from "Answers"
where code = 'q_{0}'
group by 1
order by 2 desc"""
SQL_SURVEY_SCALE_MATRIX = """select answer[3] AS AnswerCode, answer_value AS AnswerValue, count(vote_id) AS VoteCount
from (select regexp_split_to_array(code, '_') AS answer_parts, *
      from "Answers"
      where code like 'q\_{0}\_%') AS dt(answer)
group by 1, 2
order by 1, 3 desc"""
SQL_SURVEY_PARTICIPATION = r"""select count(*), date(datestamp) from "Votes"
group by date(datestamp)
order by date(datestamp);"""


def _flatten_choices(choices):
    # parent
    result = dict([(k, choices[k]['title']) for k in list(choices.keys())])
    for choice_name, choice in choices.items():
        if 'choices' not in choice:
            continue
        children = _flatten_choices(choice['choices'])
        for child_name, child_title in children.items():
            result[child_name] = child_title
    return result


def _make_table(title, cols, rows):
    table = tabulate(rows, headers=cols, tablefmt='pipe')
    if title:
        table = f"## *{title}*\n\n" + table
    return table


def _survey_question(self, questions, question_id):
    question = questions[question_id - 1]
    title = question['title']
    if question['kind'] in ('checktree', 'checkbox', 'tree', 'radio'):
        cols, rows = self._survey_database_query(SQL_SURVEY_PREFILLED_ANSWERS.format(question_id))
        choices = {}
        if question['kind'] in ('tree', 'checktree'):
            # flatten choices tree
            choices = self._flatten_choices(question['choices'])
        elif question['kind'] in ('radio', 'checkbox'):
            choices = question['choices']
        rows = [self._translate_choice(choices, row) for row in rows]
        cols = ["Vote Value", "Vote Count"]
    elif question['kind'] in ('text', 'textarea'):
        cols, rows = self._survey_database_query(SQL_SURVEY_TEXT.format(question_id))
    elif question['kind'] in ('scale-matrix',):
        cols, rows = self._survey_database_query(SQL_SURVEY_SCALE_MATRIX.format(question_id))
        rows = [self._translate_matrix(question['choices'], question['lines'], row) for row in rows]
    else:
        cols = ['Message']
        rows = [('Not implemented',)]
    return title, cols, rows


def _survey_database_query(sql):
    database_url = os.environ['QUESTIONNAIRE_DATABASE_URL']
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            cols = [col.name for col in cur.description]
    return cols, rows


def _translate_choice(choices, row):
    choice_value = row[0]
    choice_other = row[1]
    choice_count = row[2]
    if choice_value == 'text':
        choice_value = 'Other:' + choice_other
    elif choice_value is None:
        choice_value = choices.get(choice_other)
    else:
        choice_value = choices.get(choice_value)
    return choice_value, choice_count


def _translate_matrix(choices, lines, row):
    line = int(row[0])
    answer = int(row[1])
    count = row[2]
    answer_key = list(choices.keys())[answer - 1]
    return lines[line - 1] or '<empty>', choices[answer_key], count


def _truncate(text, length):
    if len(text) <= length:
        return text
    else:
        return text[:length - 3] + '...'


@gyrobot.group('survey')
@click.pass_context
def survey(ctx: ExtendedContext):
    """Get results from survey"""
    if 'QUESTIONNAIRE_DATABASE_URL' not in os.environ:
        ctx.chat.send_text('No questionnaire found', is_error=True)
        return
    if 'QUESTIONNAIRE_FILE' not in os.environ:
        ctx.chat.send_text('No questionnaire file defined', is_error=True)
        return
    questionnaire_file = pathlib.Path('data') / os.environ['QUESTIONNAIRE_FILE']
    if not questionnaire_file.exists():
        ctx.chat.send_text('No questionnaire file found', is_error=True)
        return
    with questionnaire_file.open(encoding='utf8') as qf:
        questionnaire_data = list(yaml.load_all(qf))
    questions = [q for q in questionnaire_data if q['kind'] not in ('config', 'header')]
    question_ids = [f'q_{1 + i}' for i in range(len(questions))]
    ctx.obj['questions'] = questions
    ctx.obj['question_ids'] = question_ids
    args = ctx.args
    if len(args) == 0:
        args = ['']
    title = None
    if args[0] == 'mods':
        args[0] = 'q_60'
    if args[0] == 'count':
        sql = 'SELECT COUNT(*) FROM "Votes"'
        result_type = 'single'
        _, rows = _survey_database_query(sql)
    elif args[0] in ('questions', 'questions_full'):
        trunc_length = 60 if args[0] == 'questions' else 200
        result_type = 'table'
        cols = ['Question Number', 'Type', 'Title']
        rows = [(f"\u266f{1 + i}", q['kind'], _truncate(q['title'], trunc_length)) for i, q in
                enumerate(questions)]
    elif args[0] == 'votes_per_day':
        sql = SQL_SURVEY_PARTICIPATION
        result_type = 'table'
        cols, rows = _survey_database_query(sql)
    elif args[0] in question_ids:
        question_id = int(args[0].split('_')[-1])
        result_type = 'table'
        title, cols, rows = _survey_question(questions, question_id)
    elif args[0] == 'full_replies':
        result_type = 'full_table'
        if len(args) > 1 and args[1] == 'json':
            result_type = 'full_table_json'
        result = []
        for question_text_id in question_ids:
            question_id = int(question_text_id.split('_')[-1])
            title, cols, rows = _survey_question(questions, question_id)
            result.append({'title': title, 'question_code': question_text_id, 'cols': cols, 'rows': rows})
    else:
        valid_queries = ['count', 'questions', 'questions_full', 'mods', 'votes_per_day', 'full_replies'] + \
                        ['q_1', '...', f'q_{str(len(questions))}']
        valid_queries_as_code = [f"`{q}`" for q in valid_queries]
        ctx.chat.send_text(f"You need to specify a query from {', '.join(valid_queries_as_code)}", is_error=True)
        return

    if result_type == 'single':
        ctx.chat.send_text(f"*Result*: `{rows[0][0]}`")
    elif result_type == 'table':
        ctx.chat.send_table(title=title, table=[dict(zip(cols, row)) for row in rows])
    elif result_type == 'full_table':
        filedata = b''
        with tempfile.TemporaryFile() as tmpfile:
            workbook = xlsxwriter.Workbook(tmpfile)
            for question_response in result:
                worksheet = workbook.add_worksheet()
                worksheet.name = question_response['question_code']
                title = question_response['title']
                cols = question_response['cols']
                rows = question_response['rows']

                worksheet.write('A1', title)
                for col_number, col in enumerate(cols):
                    worksheet.write(2, col_number, col)
                for row_number, row in enumerate(rows):
                    for col_number, col in enumerate(cols):
                        worksheet.write(3 + row_number, col_number, row[col_number])
                # table = self.make_table(title, cols, rows)
                # full_table += table + '\n\n'
            workbook.close()
            tmpfile.flush()
            tmpfile.seek(0, io.SEEK_SET)
            filedata = tmpfile.read()
        ctx.chat.send_file(filedata, filename="Survey_Results.xlsx", title="Survey Results")
    elif result_type == 'full_table_json':
        filedata = json.dumps(result)
        ctx.chat.send_file(filedata, filename='Survey_Results.json', title="Survey Results")
