import ast
import atexit
import collections
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
from dataclasses import dataclass
from logging import Logger
from typing import Optional

from codegen import indent

import ifcopenshell
import ifcopenshell.express

# Private copies of the EXPRESS schemas passed to register_schema(), by schema name.
custom_schemas: dict[str, str] = {}
# Rules compiled from those copies, by schema name.
compiled_rules: dict[str, str] = {}
rules_modules: dict[str, types.ModuleType] = {}


def register_schema(schema_path: str) -> str:
    """Parses and registers a custom EXPRESS schema so its files can be validated with express rules.

    The schema is copied into a new private directory and only that copy is used, both for
    registration and later for compiling its rules. No other file next to the schema is read.

    :param schema_path: Path to the .exp file.
    :return: The name of the registered schema.
    """
    directory = tempfile.mkdtemp(prefix="ifcopenshell-express-")
    atexit.register(shutil.rmtree, directory, ignore_errors=True)
    exp_path = os.path.join(directory, "schema.exp")
    shutil.copyfile(schema_path, exp_path)
    builder = ifcopenshell.express.parse(exp_path)
    ifcopenshell.register_schema(builder)
    name = builder.schema.name()
    custom_schemas[name] = exp_path
    compiled_rules.pop(name, None)
    rules_modules.pop(name, None)
    return name


def get_rules_path(schema_name: str) -> Optional[str]:
    """Returns the path of the bundled rules for a schema, or of the rules compiled from a
    schema passed to register_schema(). Returns None if neither exists."""
    if schema_name in custom_schemas:
        if schema_name not in compiled_rules:
            exp_path = custom_schemas[schema_name]
            directory = os.path.dirname(exp_path)
            rules_path = os.path.join(directory, "rules.py")
            subprocess.run(
                [sys.executable, "-m", "ifcopenshell.express.rule_compiler", exp_path, rules_path],
                check=True,
                cwd=directory,
            )
            compiled_rules[schema_name] = rules_path
        return compiled_rules[schema_name]
    rules_path = os.path.join(os.path.dirname(__file__), "rules", f"{schema_name}.py")
    if os.path.isfile(rules_path):
        return rules_path


def get_rules_module(schema_name: str) -> Optional[types.ModuleType]:
    """Imports the rules returned by get_rules_path() for a custom schema by their file path."""
    if schema_name not in rules_modules:
        if schema_name not in custom_schemas or not (rules_path := get_rules_path(schema_name)):
            return None
        spec = importlib.util.spec_from_file_location(f"{schema_name}_rules", rules_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        rules_modules[schema_name] = module
    return rules_modules[schema_name]


def reverse_compile(s):
    return re.sub(
        r"\bself\b",
        "SELF",
        re.sub(
            r"\s*\-\s*EXPRESS_ONE_BASED_INDEXING",
            "",
            re.sub(
                ", )?+.(, INDETERMINATE)\\"[::-1],
                "]\\1[",
                re.sub(
                    r", '(\w+)', INDETERMINATE\)",
                    ".\\1",
                    s.strip()
                    .replace("len(", "SIZEOF(")
                    .replace("assert ", "")
                    .replace(" is not False", "")
                    .replace("express_getattr(", "")
                    .replace("express_getitem(", ""),
                )[::-1],
            )[::-1],
        ),
    )


@dataclass
class error(Exception):
    rule_name: str
    rule_definition: str
    violation: str
    instance: ifcopenshell.entity_instance = None

    def __str__(self):
        inst = ""
        if self.instance:
            inst = f"On instance:\n{indent(4, str(self.instance))}\n"
        if self.rule_name:
            return f"{inst}Rule {self.rule_name}:\n{indent(4, self.rule_definition)}\nViolated by:\n{indent(4, self.violation)}"
        else:
            if inst:
                inst = f"\n\n{inst}"
            return f"{self.rule_definition}\n\nViolated by:\n{indent(4, self.violation)}{inst}"


def fix_type(v):
    if isinstance(v, (list, tuple)):
        # 1-based indexing:
        #
        # @todo this is not the best way, because it still allows to index the 0-th element,
        # but given the existing body of rules this should be sufficient.
        # return type(v)([None]) + type(v)(map(fix_type, v))

        # We don't do this anymore, because it doesn't fix instance attribute lookups
        # We now instead perform a -1 on the index qualifier in the code generation
        pass
    # @todo enrich entity instances with code to evaluate derived attributes
    return v


def run(f: ifcopenshell.file, logger: Logger) -> None:
    from _pytest import assertion

    fn = get_rules_path(f.schema_identifier)
    if fn is None:
        logger.error(
            f"No express rules available for schema {f.schema_identifier}. "
            "Custom schemas need to be registered with ifcopenshell.express.rule_executor.register_schema()."
        )
        return
    with open(fn, "r") as rules_file:
        source = rules_file.read()

    if hasattr(logger, "set_instance"):
        # when using the json logger, we notify it of the relevant instance
        pre_annotate_instance = lambda instance: (
            logger.set_state("instance", instance) if hasattr(logger, "set_state") else None
        )
        post_annotate_instance = lambda instance: instance
        pre_annotate_attribute = lambda attribute: (
            logger.set_state("attribute", attribute) if hasattr(logger, "set_state") else None
        )
        post_annotate_attribute = lambda attribute: None
    else:
        # when using the normal text logger the instance is appended to the method
        pre_annotate_instance = lambda instance: None
        post_annotate_instance = lambda instance: instance
        pre_annotate_attribute = lambda attribute: None
        post_annotate_attribute = lambda attribute: attribute

    orig = ifcopenshell.settings.unpack_non_aggregate_inverses
    ifcopenshell.settings.unpack_non_aggregate_inverses = True

    # Rules are transpiled with EXPRESS `=` emitted as Python `==`, so `==` has
    # to mean value comparison for the duration. See the @todo on
    # rule_compiler.process_rel_op.
    orig_compare = ifcopenshell.settings.compare_instances_by_value
    ifcopenshell.settings.compare_instances_by_value = True

    a = ast.parse(source)
    assertion.rewrite.rewrite_asserts(mod=a, source=source)
    cd = compile(a, f"{f.schema_identifier}.py", "exec")
    scope = {}
    exec(cd, scope)
    S = ifcopenshell.ifcopenshell_wrapper.schema_by_name(f.schema_identifier)

    rules = list(filter(lambda x: hasattr(x, "SCOPE"), scope.values()))

    if hasattr(logger, "set_state"):
        logger.set_state("type", "global_rule")

    for R in [r for r in rules if r.SCOPE == "file"]:
        try:
            R()(f)
        except RecursionError as e:
            logger.info(str(e))
        except Exception as e:
            ln = e.__traceback__.tb_next.tb_lineno
            pre_annotate_attribute(R.__name__)
            logger.error(
                str(
                    error(
                        post_annotate_attribute(R.__name__),
                        reverse_compile(source.split("\n")[ln - 1]),
                        reverse_compile(e.args[0]),
                    )
                )
            )

    if hasattr(logger, "set_state"):
        logger.set_state("type", "simpletype_rule")

    types = {}
    subtypes = collections.defaultdict(list)
    for d in S.declarations():
        if isinstance(d, ifcopenshell.ifcopenshell_wrapper.type_declaration):
            types[d.name()] = d
            if isinstance(d.declared_type(), ifcopenshell.ifcopenshell_wrapper.named_type):
                subtypes[d.declared_type().declared_type().name()].append(d.name())

    D = collections.defaultdict(list)
    for r in rules:
        if r.SCOPE == "type":

            def visit(nm):
                D[nm].append(r)
                for nm2 in subtypes[nm]:
                    visit(nm2)

            visit(r.TYPE_NAME)

    def type_name(ty):
        if isinstance(ty, ifcopenshell.ifcopenshell_wrapper.named_type):
            return type_name(ty.declared_type())
        elif isinstance(ty, ifcopenshell.ifcopenshell_wrapper.aggregation_type):
            # breakpoint()
            pass
        elif isinstance(ty, ifcopenshell.ifcopenshell_wrapper.simple_type):
            pass
        else:
            return ty.name()

    def check(value, type, instance):
        if value is None:
            return

        if type_name(type) in D:
            for R in D[type_name(type)]:
                try:
                    R()(fix_type(value))
                except RecursionError as e:
                    logger.info(str(e))
                except Exception as e:
                    ln = e.__traceback__.tb_next.tb_lineno
                    pre_annotate_instance(instance)
                    pre_annotate_attribute(f"{R.TYPE_NAME}.{R.RULE_NAME}")
                    logger.error(
                        str(
                            error(
                                post_annotate_attribute(f"{R.TYPE_NAME}.{R.RULE_NAME}"),
                                reverse_compile(source.split("\n")[ln - 1]),
                                reverse_compile(e.args[0]),
                                post_annotate_instance(instance),
                            )
                        )
                    )

        # @nb something can be a named type with rules and still be an aggregation.
        # case in point IfcCompoundPlaneAngleMeasure. Therefore only unpack named
        # type references from this point onwards.
        while isinstance(
            type,
            (
                ifcopenshell.ifcopenshell_wrapper.named_type,
                ifcopenshell.ifcopenshell_wrapper.type_declaration,
            ),
        ):
            type = type.declared_type()

        if isinstance(value, (list, tuple)):
            if isinstance(type, ifcopenshell.ifcopenshell_wrapper.aggregation_type):
                ty = type.type_of_element()
                for v in value:
                    check(v, ty, instance=inst)
            else:
                # Let's hope a schema validation error was reported for this case
                pass

        elif isinstance(value, ifcopenshell.entity_instance):
            if isinstance(
                S.declaration_by_name(value.is_a()),
                ifcopenshell.ifcopenshell_wrapper.entity,
            ):
                # top level entity instances will be checked on their own
                pass
            else:
                # unpack the type instance
                check(value[0], S.declaration_by_name(value.is_a()), instance=inst)

    for inst in f:
        try:
            values = list(inst)
        except RecursionError as e:
            logger.info(str(e))
        except Exception as e:
            if hasattr(logger, "set_state"):
                logger.error(str(e))
            else:
                logger.error("For instance:\n    %s\n%s", inst, e)
            continue
        entity = S.declaration_by_name(inst.is_a())
        attrs = entity.all_attributes()
        for i, (attr, val, is_derived) in enumerate(zip(attrs, values, entity.derived())):
            if is_derived:
                # @todo
                pass
            else:
                check(val, attr.type_of_attribute(), instance=inst)

    if hasattr(logger, "set_state"):
        logger.set_state("type", "entity_rule")

    for R in [r for r in rules if r.SCOPE == "entity"]:
        for inst in f.by_type(R.TYPE_NAME):
            try:
                R()(inst)
            except RecursionError as e:
                logger.info(str(e))
            except Exception as e:
                ln = e.__traceback__.tb_next.tb_lineno
                pre_annotate_instance(inst)
                pre_annotate_attribute(f"{R.TYPE_NAME}.{R.RULE_NAME}")
                logger.error(
                    str(
                        error(
                            post_annotate_attribute(f"{R.TYPE_NAME}.{R.RULE_NAME}"),
                            reverse_compile(source.split("\n")[ln - 1]),
                            reverse_compile(e.args[0]),
                            post_annotate_instance(inst),
                        )
                    )
                )

    ifcopenshell.settings.unpack_non_aggregate_inverses = orig
    ifcopenshell.settings.compare_instances_by_value = orig_compare


if __name__ == "__main__":
    import json
    import logging
    import sys

    import ifcopenshell
    from ifcopenshell.validate import json_logger

    filenames = [x for x in sys.argv[1:] if not x.startswith("--")]
    flags = set(x for x in sys.argv[1:] if x.startswith("--"))

    for fn in filenames:
        if "--json" in flags:
            logger = json_logger()
        else:
            logger = logging.getLogger("validate")
            logger.setLevel(logging.DEBUG)

        f = ifcopenshell.open(fn)

        run(f, logger)

        if "--json" in flags:
            print("\n".join(json.dumps(x, default=str) for x in logger.statements))
