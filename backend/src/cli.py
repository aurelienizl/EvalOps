"""CLI management tool for creating accounts, resetting passwords, and managing roles."""

from __future__ import annotations

import argparse
import getpass
import sys
import uuid

from .core.security import hash_password
from .db import (
    connect_db,
    create_student,
    delete_all_student_sessions,
    get_student_by_email,
    init_db,
    list_users,
    update_student_password,
    update_student_role,
)


def _prompt_password(prompt: str) -> str:
    password = getpass.getpass(prompt)
    confirm = getpass.getpass("Confirmez le mot de passe: ")
    if password != confirm:
        print("Erreur: Les mots de passe ne correspondent pas.", file=sys.stderr)
        sys.exit(1)
    if len(password) < 8:
        print("Erreur: Le mot de passe doit comporter au moins 8 caractères.", file=sys.stderr)
        sys.exit(1)
    return password


def handle_create_user(args: argparse.Namespace) -> None:
    email = args.email.strip().lower()
    if not email or "@" not in email:
        print("Erreur: Adresse email invalide.", file=sys.stderr)
        sys.exit(1)

    role = args.role

    init_db()
    with connect_db() as conn:
        existing = get_student_by_email(conn, email)
        if existing:
            print(f"Erreur: Un utilisateur avec l'email '{email}' existe déjà.", file=sys.stderr)
            sys.exit(1)

        password = _prompt_password("Mot de passe: ")
        student_id = str(uuid.uuid4())
        pwd_hash = hash_password(password)
        create_student(conn, student_id, email, pwd_hash, role=role)
        print(f"Utilisateur créé avec succès ! ID: {student_id}, Email: {email}, Rôle: {role}")


def handle_reset_password(args: argparse.Namespace) -> None:
    email = args.email.strip().lower()
    if not email:
        print("Erreur: Adresse email obligatoire.", file=sys.stderr)
        sys.exit(1)

    init_db()
    with connect_db() as conn:
        student = get_student_by_email(conn, email)
        if not student:
            print(f"Erreur: Utilisateur '{email}' introuvable.", file=sys.stderr)
            sys.exit(1)

        password = _prompt_password("Nouveau mot de passe: ")
        pwd_hash = hash_password(password)
        conn.execute("BEGIN IMMEDIATE")
        update_student_password(conn, student["id"], pwd_hash)
        # Revoke existing sessions
        delete_all_student_sessions(conn, student["id"])
        conn.commit()
        print(f"Mot de passe réinitialisé et sessions révoquées pour {email}.")


def handle_list_users(args: argparse.Namespace) -> None:
    init_db()
    with connect_db() as conn:
        rows, total = list_users(
            conn,
            search=args.search,
            role=args.role,
            limit=args.limit,
            offset=args.offset,
        )
        print(f"--- Utilisateurs ({len(rows)} affichés / {total} total) ---")
        for r in rows:
            ssh_status = "configurée" if r["ssh_public_key"] else "non configurée"
            print(f"- [{r['role'].upper()}] {r['email']} (ID: {r['id']}, Clé SSH: {ssh_status})")


def handle_set_role(args: argparse.Namespace) -> None:
    email = args.email.strip().lower()
    role = args.role.strip().lower()

    init_db()
    with connect_db() as conn:
        student = get_student_by_email(conn, email)
        if not student:
            print(f"Erreur: Utilisateur '{email}' introuvable.", file=sys.stderr)
            sys.exit(1)

        update_student_role(conn, student["id"], role)
        print(f"Rôle de l'utilisateur {email} mis à jour avec succès: {role}")


def handle_init_db(args: argparse.Namespace) -> None:
    init_db()
    print("Base de données initialisée avec succès.")


def main() -> None:
    parser = argparse.ArgumentParser(description="EvalOps CLI - Administration des comptes")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create-user
    create_parser = subparsers.add_parser("create-user", help="Créer un nouveau compte utilisateur")
    create_parser.add_argument("--email", required=True, help="Email de l'utilisateur")
    create_parser.add_argument(
        "--role", choices=["student", "admin"], default="student", help="Rôle du compte (défaut: student)"
    )
    create_parser.set_defaults(handler=handle_create_user)

    # reset-password
    reset_parser = subparsers.add_parser("reset-password", help="Réinitialiser le mot de passe d'un utilisateur")
    reset_parser.add_argument("--email", required=True, help="Email de l'utilisateur")
    reset_parser.set_defaults(handler=handle_reset_password)

    # list-users
    list_parser = subparsers.add_parser("list-users", help="Lister les comptes utilisateurs")
    list_parser.add_argument("--search", default=None, help="Filtrer par email")
    list_parser.add_argument("--role", choices=["student", "admin"], default=None, help="Filtrer par rôle")
    list_parser.add_argument("--limit", type=int, default=50, help="Nombre max d'utilisateurs (défaut: 50)")
    list_parser.add_argument("--offset", type=int, default=0, help="Décalage pagination (défaut: 0)")
    list_parser.set_defaults(handler=handle_list_users)

    # set-role
    set_role_parser = subparsers.add_parser("set-role", help="Modifier le rôle d'un utilisateur")
    set_role_parser.add_argument("--email", required=True, help="Email de l'utilisateur")
    set_role_parser.add_argument("--role", choices=["student", "admin"], required=True, help="Nouveau rôle")
    set_role_parser.set_defaults(handler=handle_set_role)

    # init-db
    subparsers.add_parser("init-db", help="Initialiser la base de données SQLite").set_defaults(handler=handle_init_db)

    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
