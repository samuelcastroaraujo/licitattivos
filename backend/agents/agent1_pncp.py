"""
Agente 1 — Edital Fetcher (PNCP)
"""

import httpx
from datetime import datetime
from models.edital import EditalCreate, Edital
from db.client import get_supabase_client
import hashlib
import structlog

log = structlog.get_logger()

async def fetch_pncp_editais(orgao_cnpj: str) -> list[EditalCreate]:
    """Busca editais no portal PNCP para o órgão fornecido e converte para EditalCreate."""
    url = f"https://pncp.gov.br/api/pncp/v1/orgaos/{orgao_cnpj}/compras"
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json().get("data", [])

    editais = []
    for item in data:
        edital = EditalCreate(
            numero_pregao=item.get("numeroCompra", ""),
            orgao=item.get("orgaoEntidade", {}).get("razaoSocial", ""),
            uf=item.get("unidadeOrçamentaria", {}).get("ufCnpj", ""),
            portal_origem="pncp",
            url_edital=item.get("linkSistemaOrigem", ""),
            status="novo"
        )
        
        # Parse de datas se existirem
        pub_date = item.get("dataPublicacaoPncp")
        if pub_date:
            edital.data_publicacao = datetime.fromisoformat(pub_date.replace("Z", "+00:00")).date()
            
        abertura = item.get("dataAberturaProposta")
        if abertura:
            edital.data_abertura = datetime.fromisoformat(abertura.replace("Z", "+00:00"))
            
        editais.append(edital)
        
    return editais

async def save_editais(editais: list[EditalCreate]) -> list[Edital]:
    """Persiste os editais no Supabase usando upsert para evitar duplicatas."""
    if not editais:
        return []
        
    client = get_supabase_client()
    
    # Prepara payload em batch
    payload = []
    for edital in editais:
        data = edital.model_dump(exclude_unset=True)
        if "data_publicacao" in data and data["data_publicacao"]:
            data["data_publicacao"] = data["data_publicacao"].isoformat()
        if "data_abertura" in data and data["data_abertura"]:
            data["data_abertura"] = data["data_abertura"].isoformat()
        payload.append(data)
        
    # Executa o upsert no Supabase
    response = client.table("editais").upsert(
        payload, 
        on_conflict="portal_origem,orgao,numero_pregao"
    ).execute()
    
    # Mapeia resposta do banco de volta para o modelo Pydantic
    saved = []
    for item in response.data:
        saved.append(Edital.model_validate(item))
        
    return saved

async def download_edital_anexo(edital: Edital) -> Edital:
    """Faz o download do anexo binário, calcula hash, envia para o Storage e atualiza o banco."""
    if not edital.anexo_url_origem:
        log.warning("edital.sem_anexo", id=str(edital.id))
        return edital
        
    client = get_supabase_client()
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient() as http_client:
                response = await http_client.get(edital.anexo_url_origem, timeout=30.0)
                response.raise_for_status()
                
                # Sucesso no download
                pdf_bytes = response.content
                hash_arquivo = hashlib.sha256(pdf_bytes).hexdigest()
                storage_path = f"editais_anexos/{edital.id}.pdf"
                
                # Upload para Supabase Storage
                client.storage.from_("editais_anexos").upload(storage_path, pdf_bytes)
                
                # Atualiza metadados no banco
                update_payload = {
                    "anexo_local_path": storage_path,
                    "hash_arquivo": hash_arquivo,
                    "status": "anexo_baixado"  # Próximo status
                }
                client.table("editais").update(update_payload).eq("id", str(edital.id)).execute()
                
                # Atualiza objeto pydantic local
                edital.anexo_local_path = storage_path
                edital.hash_arquivo = hash_arquivo
                edital.status = "anexo_baixado"
                
                return edital
                
        except Exception as e:
            log.warning("edital.download_falhou", id=str(edital.id), attempt=attempt+1, error=str(e))
            if attempt == max_retries - 1:
                # Falhou em todas as tentativas
                client.table("editais").update({"status": "erro_download"}).eq("id", str(edital.id)).execute()
                edital.status = "erro_download"
                
    return edital
