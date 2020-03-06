# -*- coding: utf-8 -*-

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.db.models import Count
from django.http import (HttpResponsePermanentRedirect,
                         HttpResponseRedirect)
from django.shortcuts import get_object_or_404, render
from django.test import modify_settings
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, View
from django.views.generic.base import TemplateView
from django.views.generic.edit import CreateView, UpdateView
from uuslug import slugify

from tcms.core.response import ModifySettingsTemplateResponse
from tcms.testcases.models import TestCasePlan
from tcms.testplans.forms import ClonePlanForm, NewPlanForm, PlanNotifyFormSet, SearchPlanForm
from tcms.testplans.models import PlanType, TestPlan
from tcms.testruns.models import TestRun


@method_decorator(permission_required('testplans.add_testplan'), name='dispatch')
class NewTestPlanView(CreateView):
    model = TestPlan
    form_class = NewPlanForm
    template_name = 'testplans/mutable.html'

    def get_form(self, form_class=None):
        form = super().get_form()
        # clear fields which are set dynamically via JavaScript
        form.populate(self.request.POST.get('product', -1))
        return form

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['initial']['author'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['notify_formset'] = kwargs.get('notify_formset') or PlanNotifyFormSet()
        return context

    def form_valid(self, form):
        notify_formset = PlanNotifyFormSet(self.request.POST)
        if notify_formset.is_valid():
            test_plan = form.save()
            notify_formset.instance = test_plan
            notify_formset.save()

            return HttpResponseRedirect(test_plan.get_absolute_url())

        # taken from FormMixin.form_invalid()
        return self.render_to_response(self.get_context_data(notify_formset=notify_formset))


@method_decorator(permission_required('testplans.change_testplan'), name='dispatch')
class Edit(UpdateView):
    model = TestPlan
    form_class = NewPlanForm
    template_name = 'testplans/mutable.html'

    def get_form(self, form_class=None):
        form = super().get_form()
        if self.request.POST.get('product'):
            form.populate(product_id=self.request.POST['product'])
        else:
            form.populate(product_id=self.object.product_id)
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['notify_formset'] = kwargs.get('notify_formset') or \
            PlanNotifyFormSet(instance=self.object)
        return context

    def form_valid(self, form):
        notify_formset = PlanNotifyFormSet(self.request.POST, instance=self.object)
        if notify_formset.is_valid():
            notify_formset.save()
            return super().form_valid(form)

        # taken from FormMixin.form_invalid()
        context_data = self.get_context_data(form=form, notify_formset=notify_formset)
        return self.render_to_response(context_data)

    def form_invalid(self, form):
        notify_formset = PlanNotifyFormSet(self.request.POST, instance=self.object)
        context_data = self.get_context_data(form=form, notify_formset=notify_formset)
        return self.render_to_response(context_data)


@method_decorator(permission_required('testplans.view_testplan'), name='dispatch')
class SearchTestPlanView(TemplateView):

    template_name = 'testplans/search.html'

    def get_context_data(self, **kwargs):
        form = SearchPlanForm(self.request.GET)
        form.populate(product_id=self.request.GET.get('product'))

        context_data = {
            'form': form,
            'plan_types': PlanType.objects.all().only('pk', 'name').order_by('name'),
        }

        return context_data


def get_number_of_plans_cases(plan_ids):
    """Get the number of cases related to each plan

    :param plan_ids: a tuple or list of TestPlans' ids
    :type plan_ids: list or tuple

    :return: a dict where key is plan_id and the value is the
        total count.
    :rtype: dict
    """
    query_set = TestCasePlan.objects.filter(plan__in=plan_ids).values('plan').annotate(
        total_count=Count('pk')).order_by('-plan')

    number_of_plan_cases = {}
    for item in query_set:
        number_of_plan_cases[item['plan']] = item['total_count']

    return number_of_plan_cases


def get_number_of_plans_runs(plan_ids):
    """Get the number of runs related to each plan

    :param plan_ids: a tuple or list of TestPlans' ids
    :type plan_ids: list or tuple

    :return: a dict where key is plan_id and the value is the
        total count.
    :rtype: dict
    """
    query_set = TestRun.objects.filter(plan__in=plan_ids).values('plan').annotate(
        total_count=Count('pk')).order_by('-plan')
    number_of_plan_runs = {}
    for item in query_set:
        number_of_plan_runs[item['plan']] = item['total_count']

    return number_of_plan_runs


def get_number_of_children_plans(plan_ids):
    """Get the number of children plans related to each plan

    :param plan_ids: a tuple or list of TestPlans' ids
    :type plan_ids: list or tuple

    :return: a dict where key is plan_id and the value is the
        total count.
    :rtype: dict
    """
    query_set = TestPlan.objects.filter(parent__in=plan_ids).values('parent').annotate(
        total_count=Count('parent')).order_by('-parent')
    number_of_children_plans = {}
    for item in query_set:
        number_of_children_plans[item['parent']] = item['total_count']

    return number_of_children_plans


def calculate_stats_for_testplans(plans):
    """Attach the number of cases and runs for each TestPlan

    :param plans: the queryset of TestPlans
    :type plans: dict
    :return: A list of TestPlans, each of which is attached the statistics which is
        with prefix cal meaning calculation result.
    :rtype: list
    """
    plan_ids = []
    for plan in plans:
        plan_ids.append(plan.pk)

    cases_counts = get_number_of_plans_cases(plan_ids)
    runs_counts = get_number_of_plans_runs(plan_ids)
    children_counts = get_number_of_children_plans(plan_ids)

    # Attach calculated statistics to each object of TestPlan
    for plan in plans:
        setattr(plan, 'cal_cases_count', cases_counts.get(plan.pk, 0))
        setattr(plan, 'cal_runs_count', runs_counts.get(plan.pk, 0))
        setattr(plan, 'cal_children_count', children_counts.get(plan.pk, 0))

    return plans


@method_decorator(permission_required('testplans.view_testplan'), name='dispatch')
class TestPlanGetView(DetailView):

    template_name = 'testplans/get.html'
    http_method_names = ['get']
    model = TestPlan
    response_class = ModifySettingsTemplateResponse

    def render_to_response(self, context, **response_kwargs):
        self.response_class.modify_settings = modify_settings(
            MENU_ITEMS={'append': [
                ('...', [
                    (
                        _('Edit'),
                        reverse('plan-edit', args=[self.object.pk])
                    ),
                    (
                        _('Clone'),
                        # todo: URL accepts POST, need to refactor to use GET+POST
                        # e.g. plans/3/clone/
                        reverse('plans-clone')
                    ),
                    (
                        _('History'),
                        "/admin/testplans/testplan/%d/history/" % self.object.pk
                    ),
                    ('-', '-'),
                    (
                        _('Delete'),
                        reverse('admin:testplans_testplan_delete', args=[self.object.pk])
                    )])]}
        )
        return super().render_to_response(context, **response_kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # todo: this can be passed to the new template and consumed
        # in the JavaScript when rendering test cases based on status
        # confirmed_status = TestCaseStatus.get_confirmed()
        return context


@method_decorator(permission_required('testplans.view_testplan'), name='dispatch')
class GetTestPlanRedirectView(DetailView):

    http_method_names = ['get']
    model = TestPlan

    def get(self, request, *args, **kwargs):
        test_plan = self.get_object()
        return HttpResponsePermanentRedirect(reverse('test_plan_url',
                                                     args=[test_plan.pk,
                                                           slugify(test_plan.name)]))


@method_decorator(permission_required('testplans.add_testplan'), name='dispatch')
class Clone(View):
    http_method_names = ['post']
    template_name = 'testplans/clone.html'

    def post(self, request):
        if 'plan' not in request.POST:
            messages.add_message(request,
                                 messages.ERROR,
                                 _('TestPlan is required'))
            # redirect back where we came from
            return HttpResponseRedirect(request.META.get('HTTP_REFERER', '/'))

        plan_id = request.POST.get('plan', 0)
        test_plan = get_object_or_404(TestPlan, pk=int(plan_id))

        post_data = request.POST.copy()
        if not request.POST.get('name'):
            post_data['name'] = test_plan.make_cloned_name()

        form = ClonePlanForm(post_data)
        form.populate(product_pk=request.POST.get('product'))

        # if required values are missing we are still going to show
        # the form below, otherwise clone & redirect
        if form.is_valid():
            form.cleaned_data['new_author'] = request.user
            cloned_plan = test_plan.clone(**form.cleaned_data)

            return HttpResponseRedirect(
                reverse('test_plan_url_short', args=[cloned_plan.pk]))

        # form wasn't valid
        context_data = {
            'test_plan': test_plan,
            'form': form,
        }

        return render(request, self.template_name, context_data)
