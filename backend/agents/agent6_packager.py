"""
Agente 6 — O Empacotador Consolidado
Recebe a suíte de documentos gerada, valida integridade, gera manifest de segurança
e empacota tudo na estrutura final para upload.
"""
import os
import zipfile
import json
import hashlib
import structlog
from typing import Dict, List

log = structlog.get_logger()

class ZeroByteFileError(Exception):
    """Exceção crítica disparada quando um arquivo de 0kb é detectado."""
    pass

def _calculate_sha256(filepath: str) -> str:
    """Calcula o hash SHA-256 do arquivo (Selo de Autenticidade)."""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        # Lê em chunks para não estourar RAM com arquivos grandes
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

async def package_documents(item_id: str, categorized_files: Dict[str, List[str]], output_dir: str) -> str:
    """Organiza os artefatos em ZIP militar, cria manifest.json e limpa temporários."""
    log.info("agent6.starting_packaging", item_id=item_id)
    
    zip_filename = f"licit_item_{item_id}_attivos.zip"
    zip_path = os.path.join(output_dir, zip_filename)
    
    manifest_data = {}
    
    # Validação rigorosa de 0kb ANTES de criar o ZIP
    for folder, files in categorized_files.items():
        for filepath in files:
            if not os.path.exists(filepath):
                continue
            if os.path.getsize(filepath) == 0:
                log.error("agent6.zero_byte_detected", filepath=filepath)
                raise ZeroByteFileError(f"Erro Crítico: Arquivo {filepath} tem 0kb. Abortando.")
                
    # Cria o ZIP
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for folder, files in categorized_files.items():
            # A estrutura já garante que pastas como juridico/ ou recursos/ só vêm se aprovadas
            for filepath in files:
                if not os.path.exists(filepath):
                    continue
                    
                filename = os.path.basename(filepath)
                # O caminho dentro do ZIP
                arcname = f"{folder}/{filename}"
                
                # Gera Hash e insere no Manifest
                file_hash = _calculate_sha256(filepath)
                manifest_data[arcname] = file_hash
                
                # Escreve arquivo no ZIP
                zf.write(filepath, arcname)
                
        # Grava o Manifest.json na raiz do ZIP
        manifest_str = json.dumps(manifest_data, indent=2)
        zf.writestr("manifest.json", manifest_str)
        
    log.info("agent6.zip_created", zip_path=zip_path, total_files=len(manifest_data))
    
    # Regra do Desapego: Limpeza militar dos rastros temporários
    for folder, files in categorized_files.items():
        for filepath in files:
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except Exception as e:
                log.warning("agent6.cleanup_failed", filepath=filepath, error=str(e))
                
    return zip_path
