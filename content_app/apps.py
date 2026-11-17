from django.apps import AppConfig



class ContentAppConfig(AppConfig):
    name = 'content_app'
    label = 'content_app'

    # overrides AppConfig.ready() to connect signals
    def ready(self):
        import content_app.signals
