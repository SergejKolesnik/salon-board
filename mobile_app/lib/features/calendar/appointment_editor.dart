import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../core/db/local_database.dart';
import 'calendar_models.dart';

class AppointmentDraft {
  const AppointmentDraft({
    required this.clientName,
    required this.phone,
    required this.service,
    required this.serviceIds,
    required this.clientId,
    required this.date,
    required this.startTime,
    required this.durationMin,
    required this.notes,
    required this.status,
  });

  final String clientName;
  final String phone;
  final String service;
  final List<int> serviceIds;
  final int? clientId;
  final String date;
  final String startTime;
  final int durationMin;
  final String notes;
  final String status;
}

class AppointmentEditor extends StatefulWidget {
  const AppointmentEditor({
    required this.database,
    required this.initialDate,
    this.appointment,
    super.key,
  });

  final LocalDatabase database;
  final DateTime initialDate;
  final CalendarAppointment? appointment;

  @override
  State<AppointmentEditor> createState() => _AppointmentEditorState();
}

class _AppointmentEditorState extends State<AppointmentEditor> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _nameController;
  late final TextEditingController _phoneController;
  late final TextEditingController _serviceController;
  late final TextEditingController _durationController;
  late final TextEditingController _notesController;
  late DateTime _date;
  late TimeOfDay _time;
  late String _status;
  late Set<int> _selectedServices;
  int? _clientId;
  List<ServiceOption> _services = const [];
  List<ClientOption> _clients = const [];
  bool _loadingReferences = true;
  bool _saving = false;

  static const _statuses = <String, String>{
    'scheduled': 'Заплановано',
    'confirmed': 'Підтверджено',
    'completed': 'Виконано',
    'cancelled': 'Скасовано',
    'no_show': 'Не прийшов',
  };

  @override
  void initState() {
    super.initState();
    final item = widget.appointment;
    final parsedDate = item == null ? null : DateTime.tryParse(item.date);
    final parts = (item?.startTime ?? '10:00').split(':');
    _date = parsedDate ?? widget.initialDate;
    _time = TimeOfDay(
      hour: int.tryParse(parts.first) ?? 10,
      minute: parts.length > 1 ? int.tryParse(parts[1]) ?? 0 : 0,
    );
    _status = item?.status ?? 'scheduled';
    _selectedServices = item?.serviceIds.toSet() ?? <int>{};
    _clientId = item?.clientId;
    _nameController = TextEditingController(text: item?.clientName ?? '');
    _phoneController = TextEditingController(text: item?.phone ?? '');
    _serviceController = TextEditingController(text: item?.service ?? '');
    _durationController = TextEditingController(
      text: (item?.durationMin ?? 60).toString(),
    );
    _notesController = TextEditingController(text: item?.notes ?? '');
    _loadReferences();
  }

  @override
  void dispose() {
    _nameController.dispose();
    _phoneController.dispose();
    _serviceController.dispose();
    _durationController.dispose();
    _notesController.dispose();
    super.dispose();
  }

  Future<void> _loadReferences() async {
    final values = await Future.wait([
      widget.database.loadServices(),
      widget.database.searchClients(''),
    ]);
    if (!mounted) return;
    setState(() {
      _services = values[0] as List<ServiceOption>;
      _clients = values[1] as List<ClientOption>;
      _loadingReferences = false;
      if (_selectedServices.isEmpty && widget.appointment == null && _services.isNotEmpty) {
        _selectedServices.add(_services.first.id);
        _updateDurationFromServices();
      }
    });
  }

  void _updateDurationFromServices() {
    final total = _services
        .where((service) => _selectedServices.contains(service.id))
        .fold<int>(0, (sum, service) => sum + service.durationMin);
    if (total > 0) _durationController.text = total.toString();
  }

  Future<void> _chooseDate() async {
    final chosen = await showDatePicker(
      context: context,
      initialDate: _date,
      firstDate: DateTime(2020),
      lastDate: DateTime(2035),
      locale: const Locale('uk'),
    );
    if (chosen != null) setState(() => _date = chosen);
  }

  Future<void> _chooseTime() async {
    final chosen = await showTimePicker(context: context, initialTime: _time);
    if (chosen != null) setState(() => _time = chosen);
  }

  void _submit() {
    if (!_formKey.currentState!.validate()) return;
    final selected = _services
        .where((service) => _selectedServices.contains(service.id))
        .toList();
    final serviceName = selected.isNotEmpty
        ? selected.map((service) => service.name).join(' + ')
        : _serviceController.text.trim();
    if (serviceName.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Оберіть або введіть послугу')),
      );
      return;
    }
    setState(() => _saving = true);
    Navigator.of(context).pop(
      AppointmentDraft(
        clientName: _nameController.text.trim(),
        phone: _phoneController.text.trim(),
        service: serviceName,
        serviceIds: selected.map((service) => service.id).toList(),
        clientId: _clientId,
        date: DateFormat('yyyy-MM-dd').format(_date),
        startTime:
            '${_time.hour.toString().padLeft(2, '0')}:${_time.minute.toString().padLeft(2, '0')}',
        durationMin: int.parse(_durationController.text.trim()),
        notes: _notesController.text.trim(),
        status: _status,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final item = widget.appointment;
    return AlertDialog(
      title: Text(item == null ? 'Новий запис' : 'Редагувати запис'),
      content: SizedBox(
        width: 480,
        child: Form(
          key: _formKey,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Autocomplete<ClientOption>(
                  displayStringForOption: (option) => option.name,
                  optionsBuilder: (value) {
                    final query = value.text.trim().toLowerCase();
                    if (query.isEmpty) {
                      return const Iterable<ClientOption>.empty();
                    }
                    return _clients.where((client) =>
                        client.name.toLowerCase().contains(query) ||
                        client.phone.toLowerCase().contains(query));
                  },
                  onSelected: (client) {
                    _nameController.text = client.name;
                    _phoneController.text = client.phone;
                    _clientId = client.id;
                  },
                  fieldViewBuilder: (context, controller, focusNode, onSubmit) {
                    if (controller.text.isEmpty && _nameController.text.isNotEmpty) {
                      controller.text = _nameController.text;
                    }
                    return TextFormField(
                      controller: controller,
                      focusNode: focusNode,
                      decoration: const InputDecoration(labelText: 'Ім’я клієнта *'),
                      textCapitalization: TextCapitalization.words,
                      validator: (value) => value == null || value.trim().isEmpty
                          ? 'Введіть ім’я клієнта'
                          : null,
                      onChanged: (value) {
                        _nameController.text = value;
                        _clientId = null;
                      },
                    );
                  },
                  optionsViewBuilder: (context, onSelected, options) => Align(
                    alignment: Alignment.topLeft,
                    child: Material(
                      elevation: 6,
                      child: SizedBox(
                        height: 220,
                        width: 340,
                        child: ListView(
                          padding: EdgeInsets.zero,
                          children: options
                              .map((client) => ListTile(
                                    title: Text(client.name),
                                    subtitle: Text(client.phone),
                                    onTap: () => onSelected(client),
                                  ))
                              .toList(),
                        ),
                      ),
                    ),
                  ),
                ),
                TextFormField(
                  controller: _phoneController,
                  decoration: const InputDecoration(labelText: 'Телефон'),
                  keyboardType: TextInputType.phone,
                ),
                const SizedBox(height: 12),
                Text('Послуги', style: Theme.of(context).textTheme.labelLarge),
                if (_loadingReferences)
                  const LinearProgressIndicator()
                else if (_services.isEmpty)
                  TextFormField(
                    controller: _serviceController,
                    decoration: const InputDecoration(labelText: 'Послуга *'),
                    validator: (value) => value == null || value.trim().isEmpty
                        ? 'Введіть назву послуги'
                        : null,
                  )
                else
                  Wrap(
                    spacing: 8,
                    children: _services
                        .map((service) => FilterChip(
                              label: Text('${service.name} · ${service.durationMin} хв'),
                              selected: _selectedServices.contains(service.id),
                              onSelected: (selected) {
                                setState(() {
                                  if (selected) {
                                    _selectedServices.add(service.id);
                                  } else {
                                    _selectedServices.remove(service.id);
                                  }
                                  _updateDurationFromServices();
                                });
                              },
                            ))
                        .toList(),
                  ),
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: _chooseDate,
                        icon: const Icon(Icons.calendar_today),
                        label: Text(DateFormat('dd.MM.yyyy').format(_date)),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: _chooseTime,
                        icon: const Icon(Icons.schedule),
                        label: Text(_time.format(context)),
                      ),
                    ),
                  ],
                ),
                TextFormField(
                  controller: _durationController,
                  decoration: const InputDecoration(labelText: 'Тривалість, хв *'),
                  keyboardType: TextInputType.number,
                  validator: (value) {
                    final duration = int.tryParse(value?.trim() ?? '');
                    return duration == null || duration < 5 || duration > 600
                        ? 'Вкажіть від 5 до 600 хвилин'
                        : null;
                  },
                ),
                DropdownButtonFormField<String>(
                  initialValue: _statuses.containsKey(_status) ? _status : 'scheduled',
                  decoration: const InputDecoration(labelText: 'Статус'),
                  items: _statuses.entries
                      .map((entry) => DropdownMenuItem(
                            value: entry.key,
                            child: Text(entry.value),
                          ))
                      .toList(),
                  onChanged: (value) => setState(() => _status = value ?? 'scheduled'),
                ),
                TextFormField(
                  controller: _notesController,
                  decoration: const InputDecoration(labelText: 'Нотатки'),
                  minLines: 1,
                  maxLines: 3,
                ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _saving ? null : () => Navigator.of(context).pop(),
          child: const Text('Скасувати'),
        ),
        FilledButton(
          onPressed: _saving ? null : _submit,
          child: Text(_saving ? 'Збереження…' : 'Зберегти'),
        ),
      ],
    );
  }
}
