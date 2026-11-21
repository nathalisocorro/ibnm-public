"""
Script de ingesta de conocimiento.

Lee un archivo markdown, genera chunks por encabezados,
crea embeddings con nomic-embed-text y los almacena en PostgreSQL.
"""

import asyncio
import argparse
import hashlib
import json
from pathlib import Path
from typing import List, Dict, Any

import ollama
from sqlalchemy import text
from ms_ob02.db.database import AsyncSessionLocal, init_db, close_db


def split_by_headings(markdown_text: str) -> List[Dict[str, Any]]:
    """
    Divide el texto markdown por encabezados.

    Args:
        markdown_text: Texto markdown completo.

    Returns:
        Lista de diccionarios con 'heading' y 'content'.
    """
    sections = []
    current_heading = ""
    current_content = []

    for line in markdown_text.split("\n"):
        # Detectar encabezados (#, ##, ###, etc.)
        if line.startswith("#"):
            # Guardar sección anterior
            if current_content:
                sections.append({
                    "heading": current_heading,
                    "content": "\n".join(current_content).strip(),
                })
            # Iniciar nueva sección
            current_heading = line.strip()
            current_content = []
        else:
            current_content.append(line)

    # Guardar última sección
    if current_content:
        sections.append({
            "heading": current_heading,
            "content": "\n".join(current_content).strip(),
        })

    return sections


def split_long_section(heading: str, content: str, max_size: int) -> List[str]:
    """
    Divide una sección larga en chunks más pequeños.

    Args:
        heading: Encabezado de la sección.
        content: Contenido de la sección.
        max_size: Tamaño máximo de caracteres por chunk.

    Returns:
        Lista de chunks.
    """
    if len(content) <= max_size:
        return [f"{heading}\n{content}" if heading else content]

    chunks = []
    # Dividir por párrafos primero
    paragraphs = content.split("\n\n")
    current_chunk = heading + "\n" if heading else ""

    for paragraph in paragraphs:
        # Si el párrafo individual es demasiado largo, dividir por caracteres
        if len(paragraph) > max_size:
            # Guardar chunk actual si tiene contenido
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
                current_chunk = ""

            # Dividir párrafo largo en trozos
            for i in range(0, len(paragraph), max_size):
                chunk = paragraph[i:i + max_size]
                chunks.append(chunk)
        else:
            # Verificar si agregar el párrafo excede el tamaño
            if len(current_chunk) + len(paragraph) + 2 > max_size:
                if current_chunk.strip():
                    chunks.append(current_chunk.strip())
                current_chunk = paragraph + "\n\n"
            else:
                current_chunk += paragraph + "\n\n"

    # Guardar último chunk
    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def generate_chunks(
    markdown_text: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> List[Dict[str, Any]]:
    """
    Genera chunks a partir del texto markdown.

    Args:
        markdown_text: Texto markdown completo.
        chunk_size: Tamaño máximo de caracteres por chunk.
        chunk_overlap: Solapamiento entre chunks (caracteres).

    Returns:
        Lista de diccionarios con 'text', 'heading' y 'index'.
    """
    sections = split_by_headings(markdown_text)
    chunks = []

    for section in sections:
        heading = section["heading"]
        content = section["content"]

        if not content:
            continue

        # Dividir sección si es demasiado larga
        section_chunks = split_long_section(heading, content, chunk_size)

        for chunk_text in section_chunks:
            if chunk_text.strip():
                chunks.append({
                    "text": chunk_text.strip(),
                    "heading": heading,
                })

    # Agregar solapamiento si es necesario
    if chunk_overlap > 0 and len(chunks) > 1:
        overlapped_chunks = []
        for i, chunk in enumerate(chunks):
            text = chunk["text"]
            # Agregar solapamiento del chunk anterior
            if i > 0:
                prev_text = chunks[i - 1]["text"]
                overlap_text = prev_text[-chunk_overlap:]
                text = overlap_text + "\n" + text
            overlapped_chunks.append({
                "text": text,
                "heading": chunk["heading"],
            })
        chunks = overlapped_chunks

    # Agregar índice
    for i, chunk in enumerate(chunks):
        chunk["index"] = i

    return chunks


async def generate_embedding(text: str) -> List[float]:
    """
    Genera embedding para un texto usando nomic-embed-text.

    Args:
        text: Texto para generar embedding.

    Returns:
        Lista de floats (vector de 768 dimensiones).
    """
    response = ollama.embeddings(
        model="nomic-embed-text",
        prompt=f"search_document: {text}",
    )
    return response["embedding"]


async def check_chunks_exist(source: str) -> bool:
    """
    Verifica si ya existen chunks para un source.

    Args:
        source: Nombre del archivo fuente.

    Returns:
        True si ya existen chunks.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT COUNT(*) FROM knowledge_chunks WHERE source = :source"),
            {"source": source},
        )
        count = result.scalar()
        return count > 0


async def insert_chunks(
    chunks: List[Dict[str, Any]],
    source: str,
    vendor: str,
    platform: str,
    technology: str,
) -> int:
    """
    Inserta chunks en la base de datos.

    Args:
        chunks: Lista de chunks a insertar.
        source: Nombre del archivo fuente.
        vendor: Fabricante.
        platform: Plataforma.
        technology: Tecnología.

    Returns:
        Número de chunks insertados.
    """
    inserted = 0

    async with AsyncSessionLocal() as session:
        for chunk in chunks:
            # Generar embedding
            embedding = await generate_embedding(chunk["text"])

            # Insertar en base de datos
            await session.execute(
                text("""
                    INSERT INTO knowledge_chunks (source, chunk_index, chunk_text, embedding, chunk_metadata, vendor, platform, technology)
                    VALUES (:source, :chunk_index, :chunk_text, :embedding, :chunk_metadata, :vendor, :platform, :technology)
                """),
                {
                    "source": source,
                    "chunk_index": chunk["index"],
                    "chunk_text": chunk["text"],
                    "embedding": str(embedding),
                    "chunk_metadata": json.dumps({
                        "heading": chunk["heading"],
                        "file": source,
                    }),
                    "vendor": vendor,
                    "platform": platform,
                    "technology": technology,
                },
            )
            inserted += 1

        await session.commit()

    return inserted


async def ingest_file(
    file_path: str,
    vendor: str,
    platform: str,
    technology: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    force: bool = False,
) -> int:
    """
    Procesa un archivo markdown y lo ingesta en la base de datos.

    Args:
        file_path: Ruta al archivo markdown.
        vendor: Fabricante.
        platform: Plataforma.
        technology: Tecnología.
        chunk_size: Tamaño máximo de caracteres por chunk.
        chunk_overlap: Solapamiento entre chunks.
        force: Si es True, elimina chunks existentes y los regenera.

    Returns:
        Número de chunks insertados.
    """
    path = Path(file_path)
    source = path.name

    # Verificar si ya existen chunks
    if not force and await check_chunks_exist(source):
        print(f"⚠️  Ya existen chunks para '{source}'. Usa --force para regenerar.")
        return 0

    # Eliminar chunks existentes si force=True
    if force:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("DELETE FROM knowledge_chunks WHERE source = :source"),
                {"source": source},
            )
            await session.commit()
        print(f"🗑️  Chunks existentes eliminados para '{source}'")

    # Leer archivo
    print(f"📖 Leyendo archivo: {file_path}")
    markdown_text = path.read_text(encoding="utf-8")

    # Generar chunks
    print(f"✂️  Generando chunks (size={chunk_size}, overlap={chunk_overlap})...")
    chunks = generate_chunks(markdown_text, chunk_size, chunk_overlap)
    print(f"📊 {len(chunks)} chunks generados")

    # Insertar en base de datos
    print(f"💾 Insertando chunks en PostgreSQL...")
    inserted = await insert_chunks(chunks, source, vendor, platform, technology)

    print(f"✅ {inserted} chunks insertados exitosamente")
    return inserted


def main():
    """Punto de entrada del script."""
    parser = argparse.ArgumentParser(
        description="Ingesta de documentos markdown en la base de conocimiento"
    )
    parser.add_argument(
        "--file",
        required=True,
        help="Ruta al archivo markdown",
    )
    parser.add_argument(
        "--vendor",
        required=True,
        help="Fabricante (cisco, huawei, juniper...)",
    )
    parser.add_argument(
        "--platform",
        required=True,
        help="Plataforma (IOS-XE, VRP, JunOS...)",
    )
    parser.add_argument(
        "--technology",
        required=True,
        help="Tecnología (CLI, NETCONF, YANG...)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1000,
        help="Tamaño máximo de caracteres por chunk (default: 1000)",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=200,
        help="Solapamiento entre chunks (default: 200)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Eliminar chunks existentes y regenerar",
    )

    args = parser.parse_args()

    # Ejecutar ingesta
    asyncio.run(ingest_file(
        file_path=args.file,
        vendor=args.vendor,
        platform=args.platform,
        technology=args.technology,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        force=args.force,
    ))


if __name__ == "__main__":
    main()
