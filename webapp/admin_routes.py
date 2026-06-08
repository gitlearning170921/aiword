# -*- coding: utf-8 -*-
"""页面4 · 超级管理员：访问密码入口与系统管理台。"""
from __future__ import annotations

from flask import Blueprint, render_template, request

from .authz import is_page13_super_admin, page4_access_required

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/admin")
@page4_access_required
def admin_page():
    """页面4：须通过页面4 访问密码验证（超级管理员）。"""
    return render_template(
        "admin.html",
        hide_main_nav=False,
        gate_page=False,
    )


def register_admin_blueprint(app):
    app.register_blueprint(admin_bp)
