#!/usr/bin/env python3
#
# Copyright (C) 2022 VyOS maintainers and contributors
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 or later as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#
# A utility to generate GraphQL schema defintions from standardized op-mode
# scripts.

import os
import sys
import json
from inspect import signature, getmembers, isfunction, isclass, getmro
from jinja2 import Template

from vyos.defaults import directories
if __package__ is None or __package__ == '':
    sys.path.append("/usr/libexec/vyos/services/api")
    from graphql.libs.op_mode import load_as_module, is_op_mode_function_name, is_show_function_name
    from graphql.libs.op_mode import snake_to_pascal_case, map_type_name
    from vyos.config import Config
    from vyos.configdict import dict_merge
    from vyos.xml import defaults
else:
    from .. libs.op_mode import load_as_module, is_op_mode_function_name, is_show_function_name
    from .. libs.op_mode import snake_to_pascal_case, map_type_name
    from .. import state

OP_MODE_PATH = directories['op_mode']
SCHEMA_PATH = directories['api_schema']
DATA_DIR = directories['data']

op_mode_include_file = os.path.join(DATA_DIR, 'op-mode-standardized.json')
op_mode_error_schema = 'op_mode_error.graphql'

if __package__ is None or __package__ == '':
    # allow running stand-alone
    conf = Config()
    base = ['service', 'https', 'api']
    graphql_dict = conf.get_config_dict(base, key_mangling=('-', '_'),
                                          no_tag_node_value_mangle=True,
                                          get_first_key=True)
    if 'graphql' not in graphql_dict:
        exit("graphql is not configured")

    graphql_dict = dict_merge(defaults(base), graphql_dict)
    auth_type = graphql_dict['graphql']['authentication']['type']
else:
    auth_type = state.settings['app'].state.vyos_auth_type

schema_data: dict = {'auth_type': auth_type,
                     'schema_name': '',
                     'schema_fields': []}

query_template  = """
{%- if auth_type == 'key' %}
input {{ schema_name }}Input {
    key: String!
    {%- for field_entry in schema_fields %}
    {{ field_entry }}
    {%- endfor %}
}
{%- elif schema_fields %}
input {{ schema_name }}Input {
    {%- for field_entry in schema_fields %}
    {{ field_entry }}
    {%- endfor %}
}
{%- endif %}

type {{ schema_name }} {
    result: Generic
}

type {{ schema_name }}Result {
    data: {{ schema_name }}
    op_mode_error: OpModeError
    success: Boolean!
    errors: [String]
}

extend type Query {
{%- if auth_type == 'key' or schema_fields %}
    {{ schema_name }}(data: {{ schema_name }}Input) : {{ schema_name }}Result @genopquery
{%- else %}
    {{ schema_name }} : {{ schema_name }}Result @genopquery
{%- endif %}
}
"""

mutation_template  = """
{%- if auth_type == 'key' %}
input {{ schema_name }}Input {
    key: String!
    {%- for field_entry in schema_fields %}
    {{ field_entry }}
    {%- endfor %}
}
{%- elif schema_fields %}
input {{ schema_name }}Input {
    {%- for field_entry in schema_fields %}
    {{ field_entry }}
    {%- endfor %}
}
{%- endif %}

type {{ schema_name }} {
    result: Generic
}

type {{ schema_name }}Result {
    data: {{ schema_name }}
    op_mode_error: OpModeError
    success: Boolean!
    errors: [String]
}

extend type Mutation {
{%- if auth_type == 'key' or schema_fields %}
    {{ schema_name }}(data: {{ schema_name }}Input) : {{ schema_name }}Result @genopmutation
{%- else %}
    {{ schema_name }} : {{ schema_name }}Result @genopquery
{%- endif %}
}
"""

error_template = """
interface OpModeError {
    name: String!
    message: String!
    vyos_code: Int!
}
{% for name in error_names %}
type {{ name }} implements OpModeError {
    name: String!
    message: String!
    vyos_code: Int!
}
{%- endfor %}
"""

def create_schema(func_name: str, base_name: str, func: callable) -> str:
    sig = signature(func)

    field_dict = {}
    for k in sig.parameters:
        field_dict[sig.parameters[k].name] = map_type_name(sig.parameters[k].annotation)

    # It is assumed that if one is generating a schema for a 'show_*'
    # function, that 'get_raw_data' is present and 'raw' is desired.
    if 'raw' in list(field_dict):
        del field_dict['raw']

    schema_fields = []
    for k,v in field_dict.items():
        schema_fields.append(k+': '+v)

    schema_data['schema_name'] = snake_to_pascal_case(func_name + '_' + base_name)
    schema_data['schema_fields'] = schema_fields

    if is_show_function_name(func_name):
        j2_template = Template(query_template)
    else:
        j2_template = Template(mutation_template)

    res = j2_template.render(schema_data)

    return res

def create_error_schema():
    from vyos import opmode

    e = Exception
    err_types = getmembers(opmode, isclass)
    err_types = [k for k in err_types if issubclass(k[1], e)]
    # drop base class, to be replaced by interface type. Find the class
    # programmatically, in case the base class name changes.
    for i in range(len(err_types)):
        if err_types[i][1] in getmro(err_types[i-1][1]):
            del err_types[i]
            break
    err_names = [k[0] for k in err_types]
    error_data = {'error_names': err_names}
    j2_template = Template(error_template)
    res = j2_template.render(error_data)

    return res

def generate_op_mode_definitions():
    out = create_error_schema()
    with open(f'{SCHEMA_PATH}/{op_mode_error_schema}', 'w') as f:
        f.write(out)

    with open(op_mode_include_file) as f:
        op_mode_files = json.load(f)

    for file in op_mode_files:
        basename = os.path.splitext(file)[0].replace('-', '_')
        module = load_as_module(basename, os.path.join(OP_MODE_PATH, file))

        funcs = getmembers(module, isfunction)
        funcs = list(filter(lambda ft: is_op_mode_function_name(ft[0]), funcs))

        funcs_dict = {}
        for (name, thunk) in funcs:
            funcs_dict[name] = thunk

        results = []
        for name,func in funcs_dict.items():
            res = create_schema(name, basename, func)
            results.append(res)

        out = '\n'.join(results)
        with open(f'{SCHEMA_PATH}/{basename}.graphql', 'w') as f:
            f.write(out)

if __name__ == '__main__':
    generate_op_mode_definitions()
