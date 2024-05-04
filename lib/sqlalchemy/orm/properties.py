# orm/properties.py
# Copyright (C) 2005-2021 the SQLAlchemy authors and contributors
# <see AUTHORS file>
#
# This module is part of SQLAlchemy and is released under
# the MIT License: http://www.opensource.org/licenses/mit-license.php

"""MapperProperty implementations.

This is a private module which defines the behavior of individual ORM-
mapped attributes.

"""

from . import attributes
from .descriptor_props import CompositeProperty
from .descriptor_props import ConcreteInheritedProperty
from .descriptor_props import SynonymProperty
from .interfaces import PropComparator
from .interfaces import StrategizedProperty
from .relationships import RelationshipProperty
from .util import _orm_full_deannotate
from .. import log
from .. import util
from ..sql import coercions
from ..sql import roles


__all__ = [
    "ColumnProperty",
    "CompositeProperty",
    "ConcreteInheritedProperty",
    "RelationshipProperty",
    "SynonymProperty",
]


@log.class_logger
class ColumnProperty(StrategizedProperty):
    """Describes an object attribute that corresponds to a table column.

    Public constructor is the :func:`_orm.column_property` function.

    """

    strategy_wildcard_key = "column"
    inherit_cache = True

    __slots__ = (
        "_orig_columns",
        "columns",
        "group",
        "deferred",
        "instrument",
        "comparator_factory",
        "descriptor",
        "active_history",
        "expire_on_flush",
        "info",
        "doc",
        "strategy_key",
        "_creation_order",
        "_is_polymorphic_discriminator",
        "_mapped_by_synonym",
        "_deferred_column_loader",
        "_raise_column_loader",
        "raiseload",
    )

    def __init__(self, *columns, **kwargs):
        r"""Provide a column-level property for use with a mapping.

        Column-based properties can normally be applied to the mapper's
        ``properties`` dictionary using the :class:`_schema.Column`
        element directly.
        Use this function when the given column is not directly present within
        the mapper's selectable; examples include SQL expressions, functions,
        and scalar SELECT queries.

        The :func:`_orm.column_property` function returns an instance of
        :class:`.ColumnProperty`.

        Columns that aren't present in the mapper's selectable won't be
        persisted by the mapper and are effectively "read-only" attributes.

        :param \*cols:
              list of Column objects to be mapped.

        :param active_history=False:
          When ``True``, indicates that the "previous" value for a
          scalar attribute should be loaded when replaced, if not
          already loaded. Normally, history tracking logic for
          simple non-primary-key scalar values only needs to be
          aware of the "new" value in order to perform a flush. This
          flag is available for applications that make use of
          :func:`.attributes.get_history` or :meth:`.Session.is_modified`
          which also need to know
          the "previous" value of the attribute.

        :param comparator_factory: a class which extends
           :class:`.ColumnProperty.Comparator` which provides custom SQL
           clause generation for comparison operations.

        :param group:
            a group name for this property when marked as deferred.

        :param deferred:
              when True, the column property is "deferred", meaning that
              it does not load immediately, and is instead loaded when the
              attribute is first accessed on an instance.  See also
              :func:`~sqlalchemy.orm.deferred`.

        :param doc:
              optional string that will be applied as the doc on the
              class-bound descriptor.

        :param expire_on_flush=True:
            Disable expiry on flush.   A column_property() which refers
            to a SQL expression (and not a single table-bound column)
            is considered to be a "read only" property; populating it
            has no effect on the state of data, and it can only return
            database state.   For this reason a column_property()'s value
            is expired whenever the parent object is involved in a
            flush, that is, has any kind of "dirty" state within a flush.
            Setting this parameter to ``False`` will have the effect of
            leaving any existing value present after the flush proceeds.
            Note however that the :class:`.Session` with default expiration
            settings still expires
            all attributes after a :meth:`.Session.commit` call, however.

        :param info: Optional data dictionary which will be populated into the
            :attr:`.MapperProperty.info` attribute of this object.

        :param raiseload: if True, indicates the column should raise an error
            when undeferred, rather than loading the value.  This can be
            altered at query time by using the :func:`.deferred` option with
            raiseload=False.

            .. versionadded:: 1.4

            .. seealso::

                :ref:`deferred_raiseload`

        .. seealso::

            :ref:`column_property_options` - to map columns while including
            mapping options

            :ref:`mapper_column_property_sql_expressions` - to map SQL
            expressions

        """
        super(ColumnProperty, self).__init__()
        self._orig_columns = [
            coercions.expect(roles.LabeledColumnExprRole, c) for c in columns
        ]
        self.columns = [
            coercions.expect(
                roles.LabeledColumnExprRole, _orm_full_deannotate(c)
            )
            for c in columns
        ]
        self.group = kwargs.pop("group", None)
        self.deferred = kwargs.pop("deferred", False)
        self.raiseload = kwargs.pop("raiseload", False)
        self.instrument = kwargs.pop("_instrument", True)
        self.comparator_factory = kwargs.pop(
            "comparator_factory", self.__class__.Comparator
        )
        self.descriptor = kwargs.pop("descriptor", None)
        self.active_history = kwargs.pop("active_history", False)
        self.expire_on_flush = kwargs.pop("expire_on_flush", True)

        if "info" in kwargs:
            self.info = kwargs.pop("info")

        if "doc" in kwargs:
            self.doc = kwargs.pop("doc")
        else:
            for col in reversed(self.columns):
                doc = getattr(col, "doc", None)
                if doc is not None:
                    self.doc = doc
                    break
            else:
                self.doc = None

        if kwargs:
            raise TypeError(
                "%s received unexpected keyword argument(s): %s"
                % (self.__class__.__name__, ", ".join(sorted(kwargs.keys())))
            )

        util.set_creation_order(self)

        self.strategy_key = (
            ("deferred", self.deferred),
            ("instrument", self.instrument),
        )
        if self.raiseload:
            self.strategy_key += (("raiseload", True),)

    @util.preload_module("sqlalchemy.orm.state", "sqlalchemy.orm.strategies")
    def _memoized_attr__deferred_column_loader(self):
        state = util.preloaded.orm_state
        strategies = util.preloaded.orm_strategies
        return state.InstanceState._instance_level_callable_processor(
            self.parent.class_manager,
            strategies.LoadDeferredColumns(self.key),
            self.key,
        )

    @util.preload_module("sqlalchemy.orm.state", "sqlalchemy.orm.strategies")
    def _memoized_attr__raise_column_loader(self):
        state = util.preloaded.orm_state
        strategies = util.preloaded.orm_strategies
        return state.InstanceState._instance_level_callable_processor(
            self.parent.class_manager,
            strategies.LoadDeferredColumns(self.key, True),
            self.key,
        )

    def __clause_element__(self):
        """Allow the ColumnProperty to work in expression before it is turned
        into an instrumented attribute.
        """

        return self.expression

    @property
    def expression(self):
        """Return the primary column or expression for this ColumnProperty.

        E.g.::


            class File(Base):
                # ...

                name = Column(String(64))
                extension = Column(String(8))
                filename = column_property(name + '.' + extension)
                path = column_property('C:/' + filename.expression)

        .. seealso::

            :ref:`mapper_column_property_sql_expressions_composed`

        """
        return self.columns[0]

    def instrument_class(self, mapper):
        if not self.instrument:
            return

        attributes.register_descriptor(
            mapper.class_,
            self.key,
            comparator=self.comparator_factory(self, mapper),
            parententity=mapper,
            doc=self.doc,
        )

    def do_init(self):
        super(ColumnProperty, self).do_init()

        if len(self.columns) > 1 and set(self.parent.primary_key).issuperset(
            self.columns
        ):
            util.warn(
                (
                    "On mapper %s, primary key column '%s' is being combined "
                    "with distinct primary key column '%s' in attribute '%s'. "
                    "Use explicit properties to give each column its own "
                    "mapped attribute name."
                )
                % (self.parent, self.columns[1], self.columns[0], self.key)
            )

    def copy(self):
        return ColumnProperty(
            deferred=self.deferred,
            group=self.group,
            active_history=self.active_history,
            *self.columns
        )

    def _getcommitted(
        self, state, dict_, column, passive=attributes.PASSIVE_OFF
    ):
        return state.get_impl(self.key).get_committed_value(
            state, dict_, passive=passive
        )

    def merge(
        self,
        session,
        source_state,
        source_dict,
        dest_state,
        dest_dict,
        load,
        _recursive,
        _resolve_conflict_map,
    ):
        if not self.instrument:
            return
        elif self.key in source_dict:
            value = source_dict[self.key]

            if not load:
                dest_dict[self.key] = value
            else:
                impl = dest_state.get_impl(self.key)
                impl.set(dest_state, dest_dict, value, None)
        elif dest_state.has_identity and self.key not in dest_dict:
            dest_state._expire_attributes(
                dest_dict, [self.key], no_loader=True
            )

    class Comparator(util.MemoizedSlots, PropComparator):
        """Produce boolean, comparison, and other operators for
        :class:`.ColumnProperty` attributes.

        See the documentation for :class:`.PropComparator` for a brief
        overview.

        .. seealso::

            :class:`.PropComparator`

            :class:`.ColumnOperators`

            :ref:`types_operators`

            :attr:`.TypeEngine.comparator_factory`

        """

        __slots__ = "__clause_element__", "info", "expressions"

        def _orm_annotate_column(self, column):
            """annotate and possibly adapt a column to be returned
            as the mapped-attribute exposed version of the column.

            The column in this context needs to act as much like the
            column in an ORM mapped context as possible, so includes
            annotations to give hints to various ORM functions as to
            the source entity of this column.   It also adapts it
            to the mapper's with_polymorphic selectable if one is
            present.

            """

            pe = self._parententity
            annotations = {
                "entity_namespace": pe,
                "parententity": pe,
                "parentmapper": pe,
                "orm_key": self.prop.key,
            }

            col = column

            # for a mapper with polymorphic_on and an adapter, return
            # the column against the polymorphic selectable.
            # see also orm.util._orm_downgrade_polymorphic_columns
            # for the reverse operation.
            if self._parentmapper._polymorphic_adapter:
                mapper_local_col = col
                col = self._parentmapper._polymorphic_adapter.traverse(col)

                # this is a clue to the ORM Query etc. that this column
                # was adapted to the mapper's polymorphic_adapter.  the
                # ORM uses this hint to know which column its adapting.
                annotations["adapt_column"] = mapper_local_col

            return col._annotate(annotations)._set_propagate_attrs(
                {"compile_state_plugin": "orm", "plugin_subject": pe}
            )

        def _memoized_method___clause_element__(self):
            if self.adapter:
                return self.adapter(self.prop.columns[0], self.prop.key)
            else:
                return self._orm_annotate_column(self.prop.columns[0])

        def _memoized_attr_info(self):
            """The .info dictionary for this attribute."""

            ce = self.__clause_element__()
            try:
                return ce.info
            except AttributeError:
                return self.prop.info

        def _memoized_attr_expressions(self):
            """The full sequence of columns referenced by this
            attribute, adjusted for any aliasing in progress.

            .. versionadded:: 1.3.17

            """
            if self.adapter:
                return [
                    self.adapter(col, self.prop.key)
                    for col in self.prop.columns
                ]
            else:
                return [
                    self._orm_annotate_column(col) for col in self.prop.columns
                ]

        def _fallback_getattr(self, key):
            """proxy attribute access down to the mapped column.

            this allows user-defined comparison methods to be accessed.
            """
            return getattr(self.__clause_element__(), key)

        def operate(self, op, *other, **kwargs):
            return op(self.__clause_element__(), *other, **kwargs)

        def reverse_operate(self, op, other, **kwargs):
            col = self.__clause_element__()
            return op(col._bind_param(op, other), col, **kwargs)

    def __str__(self):
        return str(self.parent.class_.__name__) + "." + self.key
