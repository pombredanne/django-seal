from __future__ import unicode_literals

import warnings

from django.contrib.contenttypes.fields import (
    GenericForeignKey, ReverseGenericManyToOneDescriptor,
)
from django.db.models.fields import DeferredAttribute
from django.db.models.fields.related import (
    ForwardManyToOneDescriptor, ForwardOneToOneDescriptor,
    ManyToManyDescriptor, ReverseManyToOneDescriptor,
    ReverseOneToOneDescriptor,
)
from django.utils.functional import cached_property

from .exceptions import UnsealedAttributeAccess


def _bare_repr(instance):
    return '<%s instance>' % instance.__class__.__name__


def create_sealable_related_manager(related_manager_cls, field_name):
    class SealableRelatedManager(related_manager_cls):
        def get_queryset(self):
            if getattr(self.instance._state, 'sealed', False):
                try:
                    prefetch_cache_name = self.prefetch_cache_name
                except AttributeError:
                    prefetch_cache_name = self.field.related_query_name()
                try:
                    return self.instance._prefetched_objects_cache[prefetch_cache_name]
                except (AttributeError, KeyError):
                    message = 'Cannot fetch many-to-many field %s on sealed %s.' % (
                        field_name, _bare_repr(self.instance),
                    )
                    warnings.warn(message, category=UnsealedAttributeAccess, stacklevel=3)
            return super(SealableRelatedManager, self).get_queryset()
    return SealableRelatedManager


class SealableDeferredAttribute(DeferredAttribute):
    def __get__(self, instance, cls=None):
        if instance is None:
            return self
        if (getattr(instance._state, 'sealed', False) and
            instance.__dict__.get(self.field_name, self) is self and
                self._check_parent_chain(instance, self.field_name) is None):
            message = 'Cannot fetch deferred field %s on sealed %s.' % (self.field_name, _bare_repr(instance))
            warnings.warn(message, category=UnsealedAttributeAccess, stacklevel=2)
        return super(SealableDeferredAttribute, self).__get__(instance, cls)


class SealableForwardOneToOneDescriptor(ForwardOneToOneDescriptor):
    def get_object(self, instance):
        sealed = getattr(instance._state, 'sealed', False)
        if sealed:
            from .models import SealableModel
            rel_model = self.field.remote_field.model
            if self.field.remote_field.parent_link and issubclass(rel_model, SealableModel):
                deferred = instance.get_deferred_fields()
                # Because it's a parent link, all the data is available in the
                # instance, so populate the parent model with this data.

                fields = {field.attname for field in rel_model._meta.concrete_fields}

                # If any of the related model's fields are deferred, prevent
                # the query from being performed.
                if any(field in fields for field in deferred):
                    message = 'Cannot fetch related field %s on sealed %s.' % (self.field.name, _bare_repr(instance))
                    warnings.warn(message, category=UnsealedAttributeAccess, stacklevel=3)
                else:
                    # When none of the fields inherited from the parent link
                    # are deferred ForwardOneToOneDescriptor.get_object() simply
                    # create an in-memory object from the existing field values.
                    # Make sure this in-memory instance is sealed as well.
                    obj = super(SealableForwardOneToOneDescriptor, self).get_object(instance)
                    obj.seal()
                    return obj
            else:
                message = 'Cannot fetch related field %s on sealed %s.' % (self.field.name, _bare_repr(instance))
                warnings.warn(message, category=UnsealedAttributeAccess, stacklevel=3)
        return super(SealableForwardOneToOneDescriptor, self).get_object(instance)


class SealableReverseOneToOneDescriptor(ReverseOneToOneDescriptor):
    def get_queryset(self, instance, **hints):
        if getattr(instance._state, 'sealed', False):
            message = 'Cannot fetch related field %s on sealed %s.' % (self.related.name, _bare_repr(instance))
            warnings.warn(message, category=UnsealedAttributeAccess, stacklevel=3)
        return super(SealableReverseOneToOneDescriptor, self).get_queryset(instance=instance, **hints)


class SealableForwardManyToOneDescriptor(ForwardManyToOneDescriptor):
    def get_object(self, instance):
        if getattr(instance._state, 'sealed', False):
            message = 'Cannot fetch related field %s on sealed %s.' % (self.field.name, _bare_repr(instance))
            warnings.warn(message, category=UnsealedAttributeAccess, stacklevel=3)
        return super(SealableForwardManyToOneDescriptor, self).get_object(instance)


class SealableReverseManyToOneDescriptor(ReverseManyToOneDescriptor):
    @cached_property
    def related_manager_cls(self):
        related_manager_cls = super(SealableReverseManyToOneDescriptor, self).related_manager_cls
        return create_sealable_related_manager(related_manager_cls, self.rel.name)


class SealableManyToManyDescriptor(ManyToManyDescriptor):
    @cached_property
    def related_manager_cls(self):
        related_manager_cls = super(SealableManyToManyDescriptor, self).related_manager_cls
        field_name = self.rel.name if self.reverse else self.field.name
        return create_sealable_related_manager(related_manager_cls, field_name)


class SealableGenericForeignKey(GenericForeignKey):
    def __get__(self, instance, cls=None):
        if instance is None:
            return self

        if getattr(instance._state, 'sealed', False) and not self.is_cached(instance):
            message = 'Cannot fetch related field %s on sealed %s.' % (self.name, _bare_repr(instance))
            warnings.warn(message, category=UnsealedAttributeAccess, stacklevel=2)

        return super(SealableGenericForeignKey, self).__get__(instance, cls=cls)


class SealableReverseGenericManyToOneDescriptor(ReverseGenericManyToOneDescriptor):
    @cached_property
    def related_manager_cls(self):
        related_manager_cls = super(SealableReverseGenericManyToOneDescriptor, self).related_manager_cls
        return create_sealable_related_manager(related_manager_cls, self.field.name)


sealable_descriptor_classes = {
    DeferredAttribute: SealableDeferredAttribute,
    ForwardOneToOneDescriptor: SealableForwardOneToOneDescriptor,
    ReverseOneToOneDescriptor: SealableReverseOneToOneDescriptor,
    ForwardManyToOneDescriptor: SealableForwardManyToOneDescriptor,
    ReverseManyToOneDescriptor: SealableReverseManyToOneDescriptor,
    ManyToManyDescriptor: SealableManyToManyDescriptor,
    GenericForeignKey: SealableGenericForeignKey,
    ReverseGenericManyToOneDescriptor: SealableReverseGenericManyToOneDescriptor,
}
