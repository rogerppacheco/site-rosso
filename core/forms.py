from django import forms
from .models import Cdoi  # <--- Importando o nome correto agora
from .services import verificar_whatsapp_existente

class CdoiForm(forms.ModelForm):
    class Meta:
        model = Cdoi
        # Liste os campos que aparecem no formulário
        fields = ['contato', 'descricao', 'cliente'] # Adicione os outros campos do seu model aqui

    def clean_contato(self):
        """
        Valida o campo 'contato'. O nome do método deve ser clean_<nome_do_campo>
        """
        numero = self.cleaned_data.get('contato')
        
        # Chama o serviço de verificação
        tem_whatsapp = verificar_whatsapp_existente(numero)
        
        if not tem_whatsapp:
            raise forms.ValidationError(
                "Este número não possui conta no WhatsApp. "
                "Informe um número válido para prosseguir."
            )
            
        return numero