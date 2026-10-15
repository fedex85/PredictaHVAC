"""Clientes e instalaciones (gestión) y avisos para gerentes y administradores."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core import auditoria
from core.forms import ClienteForm, InstalacionForm
from core.models import Aviso, Cliente, Instalacion, RegistroActividad
from core.permisos import ROLES_GESTION, rol_requerido


@rol_requerido(*ROLES_GESTION)
def clientes_view(request):
    form_cliente, form_inst = ClienteForm(prefix='c'), InstalacionForm(prefix='i')
    if request.method == 'POST':
        if 'c-nombre' in request.POST:
            form_cliente = ClienteForm(request.POST, prefix='c')
            if form_cliente.is_valid():
                c = form_cliente.save()
                auditoria.registrar(RegistroActividad.ADMIN_DJANGO, request, detalle=f'Alta cliente: {c.nombre}')
                messages.success(request, f'Cliente «{c.nombre}» creado.')
                return redirect('clientes')
        else:
            form_inst = InstalacionForm(request.POST, prefix='i')
            if form_inst.is_valid():
                i = form_inst.save()
                auditoria.registrar(RegistroActividad.ADMIN_DJANGO, request, detalle=f'Alta instalación: {i}')
                messages.success(request, f'Instalación «{i.nombre}» creada.')
                return redirect('clientes')
    clientes = Cliente.objects.prefetch_related('instalaciones').order_by('nombre')
    return render(request, 'clientes.html', {'clientes': clientes, 'form_cliente': form_cliente,
                                             'form_inst': form_inst, 'seccion': 'clientes'})


@rol_requerido(*ROLES_GESTION)
def cliente_editar_view(request, cliente_id):
    cliente = get_object_or_404(Cliente, pk=cliente_id)
    form = ClienteForm(request.POST or None, instance=cliente)
    if request.method == 'POST' and form.is_valid():
        form.save()
        auditoria.registrar(RegistroActividad.ADMIN_DJANGO, request, detalle=f'Cambio cliente: {cliente.nombre}')
        messages.success(request, 'Cliente actualizado. Los cambios no afectan a las órdenes ya finalizadas.')
        return redirect('clientes')
    return render(request, 'cliente_form.html', {'form': form, 'cliente': cliente, 'seccion': 'clientes'})


@rol_requerido(*ROLES_GESTION)
def avisos_view(request):
    avisos = list(Aviso.objects.filter(usuario=request.user).select_related('orden')[:100])
    return render(request, 'avisos.html', {'avisos': avisos, 'seccion': 'avisos'})


@login_required
@require_POST
def avisos_leer_view(request):
    if request.user.perfil.rol in ROLES_GESTION or request.user.is_superuser:
        Aviso.objects.filter(usuario=request.user, leido=False).update(leido=True)
    return redirect('avisos')
