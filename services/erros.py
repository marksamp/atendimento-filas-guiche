"""
Exceções de regra de negócio (mensagem segura para a tela).
São recusas esperadas, não falhas: o log as registra sem traceback.
"""


class ErroNegocio(Exception):
    """Base para recusas de regra de negócio (mensagem já pronta para o usuário)."""
