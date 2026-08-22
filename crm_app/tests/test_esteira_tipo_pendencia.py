# -*- coding: utf-8 -*-
from django.test import SimpleTestCase

from crm_app.serializers import VendaSerializer


class MotivoPendenciaTipoSerializerTest(SimpleTestCase):
    def test_campo_motivo_pendencia_tipo_no_serializer(self):
        fields = VendaSerializer.Meta.fields
        self.assertIn('motivo_pendencia_tipo', fields)
        self.assertIn('motivo_pendencia_nome', fields)
