from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from core.models import EquipoHVAC, HistorialMantenimiento, OrdenTrabajo, PerfilUsuario


class EquipoHVACForm(forms.ModelForm):
    """Alta de equipos HVAC desde el formulario 'Crear equipo'."""
    class Meta:
        model = EquipoHVAC
        fields = ['nombre', 'codigo_identificador', 'tipo', 'ubicacion', 'modelo', 'capacidad', 'refrigerante', 'fecha_instalacion',
                  'periodicidad_meses']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['periodicidad_meses'].choices = [('', 'Sin plan')] + list(EquipoHVAC.PERIODICIDAD_CHOICES)


class HistorialMantenimientoForm(forms.ModelForm):
    """
    Formulario basado en el modelo HistorialMantenimiento para registrar
    mantenimientos preventivos o correctivos de un equipo HVAC.
    """
    class Meta:
        model = HistorialMantenimiento
        fields = ['equipo', 'tipo_mantenimiento', 'descripcion', 'fecha_mantenimiento', 'tecnico_responsable']
        widgets = {
            'equipo': forms.Select(attrs={'class': 'form-control'}),
            'tipo_mantenimiento': forms.Select(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'fecha_mantenimiento': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'tecnico_responsable': forms.TextInput(attrs={'class': 'form-control'}),
        }


class EquipoHVACEditForm(forms.ModelForm):
    """Corrección de la ficha técnica de un equipo ya registrado."""
    _CLS = 'w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-500 transition'

    class Meta:
        model = EquipoHVAC
        fields = ['nombre', 'codigo_identificador', 'tipo', 'ubicacion', 'modelo', 'capacidad',
                  'refrigerante', 'estado', 'fecha_instalacion', 'periodicidad_meses']
        widgets = {'fecha_instalacion': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['periodicidad_meses'].choices = [('', 'Sin plan')] + list(EquipoHVAC.PERIODICIDAD_CHOICES)
        for campo in self.fields.values():
            campo.widget.attrs['class'] = self._CLS


_CLS_CAMPO = 'w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-500 transition'


class UsuarioBaseForm(forms.Form):
    """Datos comunes al alta y a la edición de usuarios."""
    nombre = forms.CharField(label='Nombre completo', max_length=150)
    rol = forms.ChoiceField(label='Rol', choices=PerfilUsuario.ROL_CHOICES, initial=PerfilUsuario.TECNICO)
    cert_numero = forms.CharField(label='Nº de certificado de gases fluorados', max_length=50, required=False)
    cert_categoria = forms.ChoiceField(label='Categoría', required=False,
                                       choices=[('', '—')] + PerfilUsuario.CATEGORIA_CHOICES)
    cert_caducidad = forms.DateField(label='Caducidad', required=False,
                                     widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            if not isinstance(campo.widget, forms.CheckboxInput):
                campo.widget.attrs['class'] = _CLS_CAMPO

    def clean(self):
        datos = super().clean()
        if datos.get('rol') == PerfilUsuario.ADMIN:
            # Los administradores no manipulan refrigerante: no guardan certificado.
            datos['cert_numero'], datos['cert_categoria'], datos['cert_caducidad'] = '', '', None
        else:
            numero, caducidad = datos.get('cert_numero'), datos.get('cert_caducidad')
            if numero and not caducidad:
                self.add_error('cert_caducidad', 'Indica la fecha de caducidad del certificado.')
            if caducidad and not numero:
                self.add_error('cert_numero', 'Indica el número del certificado.')
        return datos


class ContrasenaForm(UsuarioBaseForm):
    """Añade contraseña (y su repetición) validada con las reglas de Django."""
    password1 = forms.CharField(label='Contraseña', strip=False,
                                widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))
    password2 = forms.CharField(label='Repite la contraseña', strip=False,
                                widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))

    def usuario_para_validar(self, datos):
        """Usuario con el que se comparan similitudes (la contraseña no puede parecerse a sus datos)."""
        return None

    def clean(self):
        datos = super().clean()
        p1, p2 = datos.get('password1'), datos.get('password2')
        if p1 or p2:
            if p1 != p2:
                self.add_error('password2', 'Las contraseñas no coinciden.')
            else:
                try:
                    validate_password(p1, self.usuario_para_validar(datos))
                except ValidationError as e:
                    self.add_error('password1', e)
        return datos


class CrearUsuarioForm(ContrasenaForm):
    email = forms.EmailField(label='Correo electrónico')
    field_order = ['nombre', 'email', 'rol', 'password1', 'password2', 'cert_numero', 'cert_categoria', 'cert_caducidad']

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        User = get_user_model()
        if User.objects.filter(username__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Ya existe un usuario con este correo.')
        return email

    def usuario_para_validar(self, datos):
        return get_user_model()(username=datos.get('email', ''), email=datos.get('email', ''),
                                first_name=datos.get('nombre', ''))


class EditarUsuarioForm(ContrasenaForm):
    activo = forms.BooleanField(label='Cuenta activa', required=False)
    usuario_obj = None  # lo asigna la vista

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].required = False
        self.fields['password2'].required = False
        self.fields['password1'].label = 'Nueva contraseña (déjala vacía para no cambiarla)'

    def usuario_para_validar(self, datos):
        return self.usuario_obj


def _tecnicos_activos():
    """Usuarios con rol Técnico que pueden recibir órdenes."""
    return get_user_model().objects.filter(is_active=True, perfil__rol=PerfilUsuario.TECNICO).order_by('first_name', 'username')


class _NombreTecnico(forms.ModelChoiceField):
    def label_from_instance(self, usuario):
        return usuario.get_full_name() or usuario.username


def _estilar(form):
    for campo in form.fields.values():
        if not isinstance(campo.widget, forms.CheckboxInput):
            campo.widget.attrs['class'] = _CLS_CAMPO


class OrdenTrabajoForm(forms.ModelForm):
    """Alta de una orden de trabajo (el técnico es opcional: sin técnico queda Pendiente)."""
    tecnico = _NombreTecnico(queryset=get_user_model().objects.none(), required=False, empty_label='Sin asignar',
                             label='Técnico')
    sin_checklist = forms.BooleanField(required=False, label='Crear sin checklist (solo correctivas)')

    class Meta:
        model = OrdenTrabajo
        fields = ['equipo', 'tipo', 'criticidad', 'fecha_programada', 'tecnico', 'requiere_refrigerante', 'descripcion']
        widgets = {'fecha_programada': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
                   'descripcion': forms.Textarea(attrs={'rows': 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tecnico'].queryset = _tecnicos_activos()
        self.fields['equipo'].queryset = EquipoHVAC.objects.order_by('codigo_identificador')
        _estilar(self)

    def clean(self):
        from core.ordenes import certificado_problema  # evita importación circular
        datos = super().clean()
        problema = certificado_problema(datos.get('tecnico'), datos.get('requiere_refrigerante'))
        if problema:
            self.add_error('tecnico', f'No se puede asignar. {problema} Esta intervención requiere manipular refrigerante.')
        if datos.get('sin_checklist') and datos.get('tipo') != 'CORRECTIVO':
            self.add_error('sin_checklist', 'Solo las órdenes correctivas pueden crearse sin checklist.')
        return datos

    def save(self, commit=True):
        orden = super().save(commit=False)
        orden.con_checklist = not self.cleaned_data.get('sin_checklist')
        if commit:
            orden.save()
        return orden


class AsignarOrdenForm(forms.Form):
    tecnico = _NombreTecnico(queryset=get_user_model().objects.none(), label='Técnico')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tecnico'].queryset = _tecnicos_activos()
        _estilar(self)


class MotivoForm(forms.Form):
    motivo = forms.CharField(label='Motivo', widget=forms.Textarea(attrs={'rows': 3}), max_length=255)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _estilar(self)


class SubsanacionForm(MotivoForm):
    bloque = forms.ChoiceField(label='Bloque a subsanar', required=False,
                               choices=[('', 'Toda la orden')] + OrdenTrabajo.BLOQUES)


class EjecucionForm(forms.Form):
    observaciones = forms.CharField(label='Observaciones técnicas', required=False,
                                    widget=forms.Textarea(attrs={'rows': 4}))
    materiales = forms.CharField(label='Materiales utilizados', required=False,
                                 widget=forms.Textarea(attrs={'rows': 3}))
    sin_materiales = forms.BooleanField(label='Sin materiales', required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _estilar(self)
