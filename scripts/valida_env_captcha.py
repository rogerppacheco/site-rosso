import os
import sys

def check_env_var(name, required=True):
    value = os.getenv(name)
    if not value and required:
        print(f"❌ Variável obrigatória não encontrada: {name}")
        return False
    print(f"✅ {name}: {value if value else '[não definida]'}")
    return True

def main():
    print("Validação de variáveis de ambiente para reCAPTCHA e Playwright State\n")
    ok = True
    ok &= check_env_var('CAPTCHA_API_KEY')
    ok &= check_env_var('CAPTCHA_PROVIDER')
    ok &= check_env_var('SECRET_KEY')
    ok &= check_env_var('DEBUG', required=False)
    ok &= check_env_var('NIO_STORAGE_STATE', required=False)
    # Opcional: verificar se o arquivo de storage existe
    storage_path = os.getenv('NIO_STORAGE_STATE', os.path.join(os.getcwd(), '.playwright_state.json'))
    if os.path.exists(storage_path):
        print(f"✅ Arquivo de storage encontrado: {storage_path}")
    else:
        print(f"⚠️ Arquivo de storage NÃO encontrado: {storage_path}")
    if ok:
        print("\nTudo OK! Variáveis essenciais encontradas.")
        sys.exit(0)
    else:
        print("\nCorrija as variáveis acima antes de subir para produção!")
        sys.exit(1)

if __name__ == "__main__":
    main()
