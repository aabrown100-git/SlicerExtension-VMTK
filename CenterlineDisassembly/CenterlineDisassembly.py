import logging
import math
import os
from typing import Annotated, Optional

import vtk
import qt

import slicer
from slicer.i18n import tr as _
from slicer.i18n import translate
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
from slicer.parameterNodeWrapper import (
    parameterNodeWrapper,
    WithinRange,
)

from slicer import vtkMRMLScalarVolumeNode


#
# CenterlineDisassembly
#

class CenterlineDisassembly(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("Centerline disassembly")
        self.parent.categories = [translate("qSlicerAbstractCoreModule", "Vascular Modeling Toolkit")]
        self.parent.dependencies = []
        self.parent.contributors = ["Saleem Edah-Tally [Surgeon] [Hobbyist developer]"]
        self.parent.helpText = _("""
Break down a centerline model into parts.
This module makes use of the 'ExtractCenterline' module to generate curves.
See more information in the <a href="https://github.com/vmtk/SlicerExtension-VMTK/">module documentation</a>.
""")
        self.parent.acknowledgementText = _("""
This file was originally developed by Jean-Christophe Fillion-Robin, Kitware Inc., Andras Lasso, PerkLab,
and Steve Pieper, Isomics, Inc. and was partially funded by NIH grant 3P41RR013218-12S1.
""")

#
# CenterlineDisassemblyWidget
#

class CenterlineDisassemblyWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Uses ScriptedLoadableModuleWidget base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent=None) -> None:
        """
        Called when the user opens the module the first time and the widget is initialized.
        """
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)  # needed for parameter node observation
        self.logic = None
        self._parameterNode = None
        self._updatingGUIFromParameterNode = False
        self._createdCurveVisibilityAction = None

    def setup(self) -> None:
        """
        Called when the user opens the module the first time and the widget is initialized.
        """
        ScriptedLoadableModuleWidget.setup(self)

        # Load widget from .ui file (created by Qt Designer).
        # Additional widgets can be instantiated manually and added to self.layout.
        uiWidget = slicer.util.loadUI(self.resourcePath("UI/CenterlineDisassembly.ui"))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

        # Set scene in MRML widgets. Make sure that in Qt designer the top-level qMRMLWidget's
        # "mrmlSceneChanged(vtkMRMLScene*)" signal in is connected to each MRML widget's.
        # "setMRMLScene(vtkMRMLScene*)" slot.
        uiWidget.setMRMLScene(slicer.mrmlScene)

        # Create logic class. Logic implements all computations that should be possible to run
        # in batch mode, without a graphical user interface.
        self.logic = CenterlineDisassemblyLogic()
        self.ui.parameterSetSelector.addAttribute("vtkMRMLScriptedModuleNode", "ModuleName", self.moduleName)
        
        self.ui.componentCheckableComboBox.addItem(_("Bifurcations"), BIFURCATIONS_ITEM_ID)
        self.ui.componentCheckableComboBox.addItem(_("Branches"), BRANCHES_ITEM_ID)
        self.ui.componentCheckableComboBox.addItem(_("Centerlines"), CENTERLINES_ITEM_ID)
        self.ui.componentCheckableComboBox.addItem(_("Junction angles"), JUNCTION_ANGLES_ITEM_ID)
        
        # When there are too many curves, the UI is obliterated.
        # When there are a few, the curve names are nevertheless informative.
        self.ui.optionCreateCurvesMenuButton.menu().clear()
        self._createdCurveVisibilityAction = qt.QAction(_("Show curve names"))
        self._createdCurveVisibilityAction.setCheckable(True)
        self.ui.optionCreateCurvesMenuButton.menu().addAction(self._createdCurveVisibilityAction)

        # Connections

        # These connections ensure that we update parameter node when scene is closed
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

        # Update the parameter node.
        self.ui.inputCenterlineSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onCenterlineChanged)
        self.ui.parameterSetSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.setParameterNode)
        self.ui.optionCreateModelsToolButton.connect("toggled(bool)", self.onCreateModels)
        self.ui.optionCreateCurvesMenuButton.connect("toggled(bool)", self.onCreateCurves)
        self._createdCurveVisibilityAction.connect("toggled(bool)", self.onShowCurveNames)
        self.ui.componentCheckableComboBox.connect("checkedIndexesChanged()", self.onComponentSelection)
        # Buttons
        self.ui.applyButton.connect("clicked(bool)", self.onApplyButton)

        # Make sure parameter node is initialized (needed for module reload)
        self.initializeParameterNode()

    def cleanup(self) -> None:
        """
        Called when the application closes and the module widget is destroyed.
        """
        self.removeObservers()

    def enter(self) -> None:
        """
        Called each time the user opens this module.
        """
        # Make sure parameter node exists and observed
        self.initializeParameterNode()

    def exit(self) -> None:
        """
        Called each time the user opens a different module.
        """
        pass

    def onSceneStartClose(self, caller, event) -> None:
        """
        Called just before the scene is closed.
        """
        # Parameter node will be reset, do not use it anymore
        self.setParameterNode(None)

    def onSceneEndClose(self, caller, event) -> None:
        """
        Called just after the scene is closed.
        """
        # If this module is shown while the scene is closed then recreate a new parameter node immediately
        if self.parent.isEntered:
            self.initializeParameterNode()

    def initializeParameterNode(self) -> None:
        """
        Ensure parameter node exists and observed.
        """
        # Parameter node stores all user choices in parameter values, node selections, etc.
        # so that when the scene is saved and reloaded, these settings are restored.

        # The initial parameter node originates from logic and is picked up by the parameter set combobox.
        # Other parameter nodes are created by the parameter set combobox and used here.
        if not self._parameterNode:
            self.setParameterNode(self.logic.getParameterNode())
            wasBlocked = self.ui.parameterSetSelector.blockSignals(True)
            self.ui.parameterSetSelector.setCurrentNode(self._parameterNode)
            self.ui.parameterSetSelector.blockSignals(wasBlocked)

    def setParameterNode(self, inputParameterNode: slicer.vtkMRMLScriptedModuleNode) -> None:
        if inputParameterNode == self._parameterNode:
            return
        self._parameterNode = inputParameterNode

        if self._parameterNode:
            self.setDefaultParameters()
            self.updateGUIFromParameterNode()

    def setDefaultParameters(self):
        if not self._parameterNode:
            return

        # Ensure all parameters exist in the parameter node.
        # Existing parameters are not modified.
        if (not self._parameterNode.HasParameter(ROLE_CREATE_MODELS)):
            self._parameterNode.SetParameter(ROLE_CREATE_MODELS, str(0))
        if (not self._parameterNode.HasParameter(ROLE_CREATE_CURVES)):
            self._parameterNode.SetParameter(ROLE_CREATE_CURVES, str(0))
        if (not self._parameterNode.HasParameter(ROLE_SHOW_CURVE_NAMES)):
            self._parameterNode.SetParameter(ROLE_SHOW_CURVE_NAMES, str(0))
        if (not self._parameterNode.HasParameter(ROLE_CREATE_BIFURCATIONS)):
            self._parameterNode.SetParameter(ROLE_CREATE_BIFURCATIONS, str(0))
        if (not self._parameterNode.HasParameter(ROLE_CREATE_BRANCHES)):
            self._parameterNode.SetParameter(ROLE_CREATE_BRANCHES, str(0))
        if (not self._parameterNode.HasParameter(ROLE_CREATE_CENTERLINES)):
            self._parameterNode.SetParameter(ROLE_CREATE_CENTERLINES, str(0))
        if (not self._parameterNode.HasParameter(ROLE_CREATE_JUNCTION_ANGLES)):
            self._parameterNode.SetParameter(ROLE_CREATE_JUNCTION_ANGLES, str(0))

    def onApplyButton(self) -> None:
        """
        Run processing when user clicks "Apply" button.
        """
        optionCreateModels = self.ui.optionCreateModelsToolButton.checked
        optionCreateCurves = self.ui.optionCreateCurvesMenuButton.checked
        optionShowCurveNames = self._createdCurveVisibilityAction.checked
        inputCenterline = self._parameterNode.GetNodeReference(ROLE_INPUT_CENTERLINE)
        
        with slicer.util.tryWithErrorDisplay(_("Failed to compute results."), waitCursor=True):
            components = self.ui.componentCheckableComboBox.checkedIndexes()
            numberOfComponents = len(components)
            if (numberOfComponents == 0):
                raise ValueError(_("Please select the components to create."))
            
            # The junction angles are written in a table, they need neither models nor curves.
            junctionAnglesRequested = False
            for idx in range(numberOfComponents):
                if components[idx].data(qt.Qt.UserRole) == JUNCTION_ANGLES_ITEM_ID:
                    junctionAnglesRequested = True
            
            if (optionCreateModels is False) and \
                (optionCreateCurves is False) and \
                (junctionAnglesRequested is False):
                raise ValueError(_("Please specify whether centerline 'Models' and/or 'Curves' should be generated."))
            
            self.showStatusMessage( (_("Splitting centerline"),) )
            # Compute output
            self.logic.splitCenterlines(inputCenterline.GetPolyData()) # Once only for all selections
            shFolderId = -1
            
            # The total procesing time is significantly reduced when there are too many components.
            slicer.mrmlScene.StartState(slicer.mrmlScene.BatchProcessState)
            
            for idx in range(numberOfComponents): # For every selection
                modelIndex = components[idx]
                component = modelIndex.data(qt.Qt.UserRole)
                componentLabel = modelIndex.data()
                if component == BIFURCATIONS_ITEM_ID:
                    bifurcationsPolyDatas = self.logic.processGroupIds(True)
                    if (len(bifurcationsPolyDatas)):
                        if optionCreateModels:
                            shFolderId = self._createSubjectHierarchyFolderNode(componentLabel + " - " + inputCenterline.GetName() + _(" models"))
                        
                        if optionCreateCurves:
                            shCurveFolderId = self._createCurveSubjectHierarchyFolderNode(componentLabel + " - " + inputCenterline.GetName() + _(" curves"))
                    
                    self.showStatusMessage( (_("Creating bifurcations"),) )
                    for groupId, bifurcationPolyData in bifurcationsPolyDatas:
                        if optionCreateModels:
                            self._createModelComponent(bifurcationPolyData, _("Bifurcation_Model"), [0.67, 1.0, 1.0], shFolderId, groupId)
                        
                        if optionCreateCurves:
                            self._createCurveComponent(bifurcationPolyData, _("Bifurcation_Curve"),
                                                       [0.33, 0.0, 0.0], shCurveFolderId, optionShowCurveNames, groupId)
                        
                elif component == BRANCHES_ITEM_ID:
                    branchesPolyDatas = self.logic.processGroupIds(False)
                    if (len(branchesPolyDatas)):
                        if optionCreateModels:
                            shFolderId = self._createSubjectHierarchyFolderNode(componentLabel + " - " + inputCenterline.GetName() + _(" models"))
                        
                        if optionCreateCurves:
                            shCurveFolderId = self._createCurveSubjectHierarchyFolderNode(componentLabel + " - " + inputCenterline.GetName() + _(" curves"))
                    
                    self.showStatusMessage( (_("Creating branches"),) )
                    for groupId, branchPolyData in branchesPolyDatas:
                        if optionCreateModels:
                            self._createModelComponent(branchPolyData, _("Branch_Model"), [0.0, 0.0, 1.0], shFolderId, groupId)
                        
                        if optionCreateCurves:
                            self._createCurveComponent(branchPolyData, _("Branch_Curve"),
                                                       [1.0, 1.0, 0.0], shCurveFolderId, optionShowCurveNames, groupId)
                        
                elif component == JUNCTION_ANGLES_ITEM_ID:
                    self.showStatusMessage( (_("Computing junction angles"),) )
                    junctionAngles = self.logic.processJunctionAngles()
                    if (len(junctionAngles) == 0):
                        logging.warning(_("No junction angle was computed:"
                                          " the centerline does not have any bifurcation."))
                    else:
                        tableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode",
                                        slicer.mrmlScene.GenerateUniqueName(componentLabel + " - " + inputCenterline.GetName()))
                        self.logic.populateJunctionAnglesTable(tableNode, junctionAngles)
                        
                        # The segments that the angles were measured on
                        shVectorFolderId = self._createCurveSubjectHierarchyFolderNode(
                                               componentLabel + " - " + inputCenterline.GetName() + _(" vectors"))
                        for bifurcation in self.logic.computeBifurcationVectors():
                            for groupId in sorted(bifurcation["branches"].keys()):
                                self._createBifurcationVectorComponent(bifurcation["branches"][groupId],
                                                                       shVectorFolderId, optionShowCurveNames)
                        
                        # The measured angles, shown in 3D views. Several angles of a bifurcation are
                        # labelled at the same position, so they are grouped by the type of the pair of
                        # branches, which can be shown and hidden separately.
                        shAngleFolderId = self._createCurveSubjectHierarchyFolderNode(
                                              componentLabel + " - " + inputCenterline.GetName() + _(" annotations"))
                        pairTypeLabels = {"child-child": _("Child-child angles"),
                                          "parent-child": _("Parent-child angles"),
                                          "parent-parent": _("Parent-parent angles")}
                        shPairTypeFolderIds = {}
                        for junctionAngle in junctionAngles:
                            pairType = self.logic.junctionAnglePairType(junctionAngle["branch1Role"],
                                                                        junctionAngle["branch2Role"])
                            if pairType not in shPairTypeFolderIds:
                                shPairTypeFolderIds[pairType] = self._createCurveSubjectHierarchyFolderNode(
                                                                    pairTypeLabels[pairType], shAngleFolderId)
                            self._createJunctionAngleComponent(junctionAngle, shPairTypeFolderIds[pairType])
                        
                elif component == CENTERLINES_ITEM_ID:
                    centerlinesPolyDatas = self.logic.processCenterlineIds()
                    if (len(centerlinesPolyDatas)):
                        if optionCreateModels:
                            shFolderId = self._createSubjectHierarchyFolderNode(componentLabel + " - " + inputCenterline.GetName() + _(" models"))
                        
                        if optionCreateCurves:
                            shCurveFolderId = self._createCurveSubjectHierarchyFolderNode(componentLabel + " - " + inputCenterline.GetName() + _(" curves"))
                    
                    self.showStatusMessage( (_("Creating centerlines"),) )
                    for centerlinePolyData in centerlinesPolyDatas:
                        if optionCreateModels:
                            self._createModelComponent(centerlinePolyData, _("Centerline_Model"), [1.0, 0.0, 0.5], shFolderId)
                        
                        if optionCreateCurves:
                            self._createCurveComponent(centerlinePolyData, _("Centerline_Curve"),
                                                       [0.0, 1.0, 0.5], shCurveFolderId, optionShowCurveNames)
                else:
                    slicer.mrmlScene.EndState(slicer.mrmlScene.BatchProcessState)
                    message = _("Invalid component")
                    self.showStatusMessage( (message,) )
                    raise ValueError( (message,) )
            
            slicer.mrmlScene.EndState(slicer.mrmlScene.BatchProcessState)
            self.showStatusMessage( (_("Finished"),) )

    def _createSubjectHierarchyFolderNode(self, label):
        inputCenterline = self._parameterNode.GetNodeReference(ROLE_INPUT_CENTERLINE)
        if inputCenterline is None:
            return
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        shMasterCenterlineId = shNode.GetItemByDataNode(inputCenterline)
        shFolderId = shNode.CreateFolderItem(shMasterCenterlineId, label)
        shNode.SetItemExpanded(shFolderId, False)
        return shFolderId
    
    def _createCurveSubjectHierarchyFolderNode(self, label, parentFolderId = None):
        inputCenterline = self._parameterNode.GetNodeReference(ROLE_INPUT_CENTERLINE)
        if inputCenterline is None:
            return
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        shFolderId = shNode.CreateFolderItem(shNode.GetSceneItemID() if parentFolderId is None else parentFolderId,
                                             label)
        shNode.SetItemExpanded(shFolderId, False)
        return shFolderId
        
    def _reparentNodeToSubjectHierarchyFolderNode(self, shFolderId, anyObject) -> None:
        if shFolderId < 0:
            return
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        shObjectId = shNode.GetItemByDataNode(anyObject)
        shNode.SetItemParent(shObjectId, shFolderId)
    
    def _createModelComponent(self, polydata, basename, color, parentFolderId, groupId = None):
        name = slicer.mrmlScene.GenerateUniqueName(basename)
        model = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", name)
        model.CreateDefaultDisplayNodes()
        model.SetAndObservePolyData(polydata)
        model.GetDisplayNode().SetColor(color)
        if groupId is not None:
            # Tells which branch or bifurcation of the centerline this component is
            model.SetAttribute("GroupId", str(groupId))
        self._reparentNodeToSubjectHierarchyFolderNode(parentFolderId, model)
        return model
    
    def _createCurveComponent(self, polydata, basename, color, parentFolderId, showCurveName, groupId = None):
        name = slicer.mrmlScene.GenerateUniqueName(basename)
        curve = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsCurveNode", name)
        curve.CreateDefaultDisplayNodes()
        curve.GetDisplayNode().SetPropertiesLabelVisibility(showCurveName)
        self.logic.createCenterlineCurve(polydata, curve)
        curve.GetDisplayNode().SetSelectedColor(color)
        if groupId is not None:
            # Tells which branch or bifurcation of the centerline this component is
            curve.SetAttribute("GroupId", str(groupId))
        self._reparentNodeToSubjectHierarchyFolderNode(parentFolderId, curve)
        return curve

    def _createBifurcationVectorComponent(self, branch, parentFolderId, showCurveName):
        """Create a curve for the segment over which the direction of a branch was measured."""
        name = slicer.mrmlScene.GenerateUniqueName(_("Bifurcation_Vector"))
        curve = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsCurveNode", name)
        curve.CreateDefaultDisplayNodes()
        curve.GetDisplayNode().SetPropertiesLabelVisibility(showCurveName)
        curve.GetDisplayNode().SetSelectedColor([1.0, 0.5, 0.0])
        curve.SetNumberOfPointsPerInterpolatingSegment(1)
        basePosition = branch["basePosition"]
        curve.AddControlPoint(vtk.vtkVector3d(basePosition))
        curve.AddControlPoint(vtk.vtkVector3d([basePosition[i] + branch["vector"][i] for i in range(3)]))
        curve.SetAttribute("GroupId", str(branch["groupId"]))
        # A measurement result, it must not be changed by moving a control point
        curve.SetLocked(True)
        self._reparentNodeToSubjectHierarchyFolderNode(parentFolderId, curve)
        return curve

    def _createJunctionAngleComponent(self, junctionAngle, parentFolderId):
        """Create an angle markup that shows a measured angle in 3D views."""
        pairType = self.logic.junctionAnglePairType(junctionAngle["branch1Role"], junctionAngle["branch2Role"])
        colors = {"child-child": [1.0, 1.0, 0.0], "parent-child": [0.0, 1.0, 1.0], "parent-parent": [1.0, 1.0, 1.0]}
        name = slicer.mrmlScene.GenerateUniqueName(_("Junction_Angle") + "_%d-%d" % (
                   junctionAngle["branch1GroupId"], junctionAngle["branch2GroupId"]))
        angleNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsAngleNode", name)
        angleNode.CreateDefaultDisplayNodes()
        # The angle is measured at the second control point, which is the bifurcation origin
        angleNode.AddControlPoint(vtk.vtkVector3d(junctionAngle["branch1Position"]))
        angleNode.AddControlPoint(vtk.vtkVector3d(junctionAngle["junctionPosition"]))
        angleNode.AddControlPoint(vtk.vtkVector3d(junctionAngle["branch2Position"]))
        angleNode.SetAttribute("BifurcationGroupId", str(junctionAngle["bifurcationGroupId"]))
        angleNode.GetDisplayNode().SetSelectedColor(colors[pairType])
        angleNode.GetDisplayNode().SetPointLabelsVisibility(False)
        # Shows the name of the annotation and the measured angle in 3D views
        angleNode.GetDisplayNode().SetPropertiesLabelVisibility(True)
        # A measurement result, it must not be changed by moving a control point
        angleNode.SetLocked(True)
        self._reparentNodeToSubjectHierarchyFolderNode(parentFolderId, angleNode)
        return angleNode
    
    def showStatusMessage(self, messages, console = False) -> None:
        separator = " "
        msg = separator.join(messages)
        slicer.util.showStatusMessage(msg, 3000)
        slicer.app.processEvents()
        if console:
            logging.info(msg)

    def onCenterlineChanged(self, node):
        if self._parameterNode:
            self._parameterNode.SetNodeReferenceID(ROLE_INPUT_CENTERLINE, node.GetID() if node else None)

    def onCreateModels(self, checked):
        if self._parameterNode:
            self._parameterNode.SetParameter(ROLE_CREATE_MODELS, str(1) if checked else str(0))

    def onCreateCurves(self, checked):
        if self._parameterNode:
            self._parameterNode.SetParameter(ROLE_CREATE_CURVES, str(1) if checked else str(0))

    def onShowCurveNames(self, checked):
        if self._parameterNode:
            self._parameterNode.SetParameter(ROLE_SHOW_CURVE_NAMES, str(1) if checked else str(0))


    def onComponentSelection(self):
        bifurcationsModelIndex = self.ui.componentCheckableComboBox.checkableModel().index(0, 0)
        self._parameterNode.SetParameter(ROLE_CREATE_BIFURCATIONS, str(self.ui.componentCheckableComboBox.checkState(bifurcationsModelIndex)))
        
        branchesModelIndex = self.ui.componentCheckableComboBox.checkableModel().index(1, 0)
        self._parameterNode.SetParameter(ROLE_CREATE_BRANCHES, str(self.ui.componentCheckableComboBox.checkState(branchesModelIndex)))
        
        centerlinesModelIndex = self.ui.componentCheckableComboBox.checkableModel().index(2, 0)
        self._parameterNode.SetParameter(ROLE_CREATE_CENTERLINES, str(self.ui.componentCheckableComboBox.checkState(centerlinesModelIndex)))
        
        junctionAnglesModelIndex = self.ui.componentCheckableComboBox.checkableModel().index(3, 0)
        self._parameterNode.SetParameter(ROLE_CREATE_JUNCTION_ANGLES, str(self.ui.componentCheckableComboBox.checkState(junctionAnglesModelIndex)))

    def updateGUIFromParameterNode(self):
        if self._parameterNode is None or self._updatingGUIFromParameterNode:
            return

        # Make sure GUI changes do not call updateParameterNodeFromGUI (it could cause infinite loop)
        self._updatingGUIFromParameterNode = True

        self.ui.inputCenterlineSelector.setCurrentNode(self._parameterNode.GetNodeReference(ROLE_INPUT_CENTERLINE))
        self.ui.optionCreateModelsToolButton.setChecked(int(self._parameterNode.GetParameter(ROLE_CREATE_MODELS)))
        self.ui.optionCreateCurvesMenuButton.setChecked(int(self._parameterNode.GetParameter(ROLE_CREATE_CURVES)))
        self._createdCurveVisibilityAction.setChecked(int(self._parameterNode.GetParameter(ROLE_SHOW_CURVE_NAMES)))

        wasBlocked = self.ui.componentCheckableComboBox.blockSignals(True)
        bifurcationsModelIndex = self.ui.componentCheckableComboBox.checkableModel().index(0, 0)
        self.ui.componentCheckableComboBox.setCheckState(bifurcationsModelIndex, int(self._parameterNode.GetParameter(ROLE_CREATE_BIFURCATIONS)))
        
        branchesModelIndex = self.ui.componentCheckableComboBox.checkableModel().index(1, 0)
        self.ui.componentCheckableComboBox.setCheckState(branchesModelIndex, int(self._parameterNode.GetParameter(ROLE_CREATE_BRANCHES)))
        
        centerlinesModelIndex = self.ui.componentCheckableComboBox.checkableModel().index(2, 0)
        self.ui.componentCheckableComboBox.setCheckState(centerlinesModelIndex, int(self._parameterNode.GetParameter(ROLE_CREATE_CENTERLINES)))
        
        junctionAnglesModelIndex = self.ui.componentCheckableComboBox.checkableModel().index(3, 0)
        self.ui.componentCheckableComboBox.setCheckState(junctionAnglesModelIndex, int(self._parameterNode.GetParameter(ROLE_CREATE_JUNCTION_ANGLES)))
        self.ui.componentCheckableComboBox.blockSignals(wasBlocked)

        self._updatingGUIFromParameterNode = False
#
# CenterlineDisassemblyLogic
#

class CenterlineDisassemblyLogic(ScriptedLoadableModuleLogic):
    def __init__(self) -> None:
        """
        Called when the logic class is instantiated. Can be used for initializing member variables.
        """
        ScriptedLoadableModuleLogic.__init__(self)
        self._splitCenterlines = None
        self._bifurcationVectors = None

    def splitCenterlines(self, inputCenterline: vtk.vtkPolyData):

        if not inputCenterline:
            raise ValueError(_("Input centerline is invalid"))

        import vtkvmtkComputationalGeometryPython as vtkvmtkComputationalGeometry
        
        branchExtractor = vtkvmtkComputationalGeometry.vtkvmtkCenterlineBranchExtractor()
        branchExtractor.SetInputData(inputCenterline)
        branchExtractor.SetBlankingArrayName(blankingArrayName)
        branchExtractor.SetRadiusArrayName(radiusArrayName)
        branchExtractor.SetGroupIdsArrayName(groupIdsArrayName)
        branchExtractor.SetCenterlineIdsArrayName(centerlineIdsArrayName)
        branchExtractor.SetTractIdsArrayName(tractIdsArrayName)
        branchExtractor.Update()
        self._splitCenterlines = branchExtractor.GetOutput()
        self._bifurcationVectors = None
        return self._splitCenterlines

    def getNumberOfCenterlines(self):
        if not self._splitCenterlines:
            raise ValueError(_("Call 'splitCenterlines()' with an input centerline polydata first."))

        import vtkvmtkComputationalGeometryPython as vtkvmtkComputationalGeometry
        centerlineIdsArray = self._splitCenterlines.GetCellData().GetArray(centerlineIdsArrayName)
        centerlineIdsValueRange = centerlineIdsArray.GetValueRange()
        # centerlineIdsValueRange[0] is always seen as 0.
        return (centerlineIdsValueRange[1] - centerlineIdsValueRange[0]) + 1

    def getNumberOfBifurcations(self):
        # Logical bifurcations, not by anatomy.
        if not self._splitCenterlines:
            raise ValueError(_("Call 'splitCenterlines()' with an input centerline polydata first."))

        groupIdsArray = vtk.vtkIdList()
        import vtkvmtkComputationalGeometryPython as vtkvmtkComputationalGeometry
        centerlineUtilities = vtkvmtkComputationalGeometry.vtkvmtkCenterlineUtilities()
        centerlineUtilities.GetBlankedGroupsIdList(self._splitCenterlines, groupIdsArrayName,
                                                       blankingArrayName, groupIdsArray)
        return groupIdsArray.GetNumberOfIds()

    def getNumberOfBranches(self):
        # Logical branches, not by anatomy.
        if not self._splitCenterlines:
            raise ValueError(_("Call 'splitCenterlines()' with an input centerline polydata first."))

        groupIdsArray = vtk.vtkIdList()
        import vtkvmtkComputationalGeometryPython as vtkvmtkComputationalGeometry
        centerlineUtilities = vtkvmtkComputationalGeometry.vtkvmtkCenterlineUtilities()
        centerlineUtilities.GetNonBlankedGroupsIdList(self._splitCenterlines, groupIdsArrayName,
                                                       blankingArrayName, groupIdsArray)
        return groupIdsArray.GetNumberOfIds()

    def _createPolyData(self, cellIds):
        if not self._splitCenterlines:
            raise ValueError(_("Call 'splitCenterlines()' with an input centerline polydata first."))

        masterRadiusArray = self._splitCenterlines.GetPointData().GetArray(radiusArrayName)
        masterEdgeArray = self._splitCenterlines.GetPointData().GetArray(edgeArrayName)
        masterEdgePCoordArray = self._splitCenterlines.GetPointData().GetArray(edgePCoordArrayName)

        resultPolyDatas = [] # One per cell
        nbIds = cellIds.GetNumberOfIds() # Number of cells

        for i in range(nbIds): # For every cell
            unitCellPolyData = None
            pointId = 0
            # Read new{points, cellArray,...}
            points = vtk.vtkPoints()
            cellArray = vtk.vtkCellArray()
            radiusArray = vtk.vtkDoubleArray()
            radiusArray.SetName(radiusArrayName)
            if masterEdgeArray:
                edgeArray = vtk.vtkDoubleArray()
                edgeArray.SetName(edgeArrayName)
                edgeArray.SetNumberOfComponents(2)
            if masterEdgePCoordArray:
                edgePCoordArray = vtk.vtkDoubleArray()
                edgePCoordArray.SetName(edgePCoordArrayName)
            
            masterCellId = cellIds.GetId(i)
            masterCellPolyLine = self._splitCenterlines.GetCell(masterCellId)
            masterCellPointIds = masterCellPolyLine.GetPointIds()
            numberOfMasterCellPointIds = masterCellPointIds.GetNumberOfIds()
            cellArray.InsertNextCell(numberOfMasterCellPointIds)
            for idx in range(numberOfMasterCellPointIds):
                point = [0.0, 0.0, 0.0]
                masterPointId = masterCellPointIds.GetId(idx)
                self._splitCenterlines.GetPoint(masterPointId, point)
                points.InsertNextPoint(point)
                cellArray.InsertCellPoint(pointId)
                radiusArray.InsertNextValue(masterRadiusArray.GetValue(masterPointId))
                if masterEdgeArray:
                    edgeArray.InsertNextTuple2(masterEdgeArray.GetTuple2(masterPointId)[0], 
                                            masterEdgeArray.GetTuple2(masterPointId)[1])
                if masterEdgePCoordArray:
                    edgePCoordArray.InsertNextValue(masterEdgePCoordArray.GetValue(masterPointId))
                pointId = pointId + 1

            if (numberOfMasterCellPointIds):
                unitCellPolyData = vtk.vtkPolyData()
                unitCellPolyData.SetPoints(points)
                unitCellPolyData.SetLines(cellArray)
                unitCellPolyData.GetPointData().AddArray(radiusArray)
                if masterEdgeArray:
                    unitCellPolyData.GetPointData().AddArray(edgeArray)
                if masterEdgePCoordArray:
                    unitCellPolyData.GetPointData().AddArray(edgePCoordArray)
                resultPolyDatas.append(unitCellPolyData)
        return resultPolyDatas
    
    def _mergeCenterlineCells(self, centerlinePolyData):
        """
        1. ExtractCenterline::_addCenterline works on a single cellId.
        
        centerlinePolyData for bifurcations and branches always has a single cell.
        
        centerlinePolyData for centerlines has more than one cell.
        We need to merge all the cells into a single cell to pass to
        ExtractCenterline::addCenterlineCurves.
        
        2. If the centerline cells are not merged, bifurcations will be identified if the centerline
        is reprocessed here, while it does not have any bifurcation.
        """
        if not centerlinePolyData:
            raise ValueError("Centerline polydata is None.")
        if centerlinePolyData.GetNumberOfCells() == 0:
            raise ValueError("Centerline polydata does not have any cell.")
            return centerlinePolyData
        if centerlinePolyData.GetNumberOfCells() == 1:
            logging.info("Centerline polydata already has a single cell.")
            return centerlinePolyData

        masterRadiusArray = centerlinePolyData.GetPointData().GetArray(radiusArrayName)
        masterEdgeArray = centerlinePolyData.GetPointData().GetArray(edgeArrayName)
        masterEdgePCoordArray = centerlinePolyData.GetPointData().GetArray(edgePCoordArrayName)

        newPolyData = None
        pointId = 0
        # Read new{points, cellArray,...}
        points = vtk.vtkPoints()
        cellArray = vtk.vtkCellArray()
        radiusArray = vtk.vtkDoubleArray()
        radiusArray.SetName(radiusArrayName)
        if masterEdgeArray:
            edgeArray = vtk.vtkDoubleArray()
            edgeArray.SetName(edgeArrayName)
            edgeArray.SetNumberOfComponents(2)
        if masterEdgePCoordArray:
            edgePCoordArray = vtk.vtkDoubleArray()
            edgePCoordArray.SetName(edgePCoordArrayName)

        # The new cell array must allocate for points of all input cells.
        cellArray.InsertNextCell(centerlinePolyData.GetNumberOfPoints())

        for cellId in range(centerlinePolyData.GetNumberOfCells()): # For every cell
            masterCellPolyLine = centerlinePolyData.GetCell(cellId)
            masterCellPointIds = masterCellPolyLine.GetPointIds()
            numberOfMasterCellPointIds = masterCellPointIds.GetNumberOfIds()

            for idx in range(numberOfMasterCellPointIds):
                point = [0.0, 0.0, 0.0]
                masterPointId = masterCellPointIds.GetId(idx)
                centerlinePolyData.GetPoint(masterPointId, point)
                points.InsertNextPoint(point)
                cellArray.InsertCellPoint(pointId)
                radiusArray.InsertNextValue(masterRadiusArray.GetValue(masterPointId))
                if masterEdgeArray:
                    edgeArray.InsertNextTuple2(masterEdgeArray.GetTuple2(masterPointId)[0], 
                                            masterEdgeArray.GetTuple2(masterPointId)[1])
                if masterEdgePCoordArray:
                    edgePCoordArray.InsertNextValue(masterEdgePCoordArray.GetValue(masterPointId))
                pointId = pointId + 1

        # All cells from the input centerline have been processed.
        if (pointId):
            mergedPolyData = vtk.vtkPolyData()
            mergedPolyData.SetPoints(points)
            mergedPolyData.SetLines(cellArray)
            mergedPolyData.GetPointData().AddArray(radiusArray)
            if masterEdgeArray:
                mergedPolyData.GetPointData().AddArray(edgeArray)
            if masterEdgePCoordArray:
                mergedPolyData.GetPointData().AddArray(edgePCoordArray)
            """
            There are 2 pairs of duplicate points.
            Each pair consists of 2 consecutive point ids with the same coordinate.
            vtkParallelTransportFrame gives thus 2 invalid tangents of [0, 0, 0].
            The reason is yet to be found.
            """
            cleaner = vtk.vtkCleanPolyData()
            cleaner.SetInputData(mergedPolyData)
            cleaner.Update()
            newPolyData = vtk.vtkPolyData()
            newPolyData.DeepCopy(cleaner.GetOutput())

        return newPolyData

    def createCenterlineCurve(self, centerlinePolyData, curveNode):
        """
        The mergedCenterlines in createCurveTreeFromCenterline does not get a GroupIds array
        if the input polydata has fewer than 2 points.

        groupId = mergedCenterlines.GetCellData().GetArray(self.groupIdsArrayName).GetValue(cellId)
        -> AttributeError: 'NoneType' object has no attribute 'GetValue'
        """
        if (centerlinePolyData and centerlinePolyData.GetNumberOfPoints() < 3):
            logging.warning("Not enough points (<3) from polydata to create a markups curve.")
            return

        import time
        startTime = time.time()
        logging.info(_("Processing curve creation started"))

        if curveNode and centerlinePolyData:
            import ExtractCenterline
            ecLogic = ExtractCenterline.ExtractCenterlineLogic()
            ecLogic.createCurveTreeFromCenterline(centerlinePolyData, centerlineCurveNode = curveNode)
            curveName = curveNode.GetName()
            curveName = curveName[0:(len(curveName) - 4)] # Remove ' (0)'
            curveNode.SetName(curveName)

        stopTime = time.time()
        durationValue = '%.2f' % (stopTime-startTime)
        logging.info(_("Processing curve creation completed in {duration} seconds").format(duration=durationValue))
    
    def processCenterlineIds(self):

        if not self._splitCenterlines:
            raise ValueError(_("Call 'splitCenterlines()' with an input centerline polydata first."))

        import time
        startTime = time.time()
        logging.info(_("Processing centerline ids started"))

        centerlinePolyDatas = []
        import vtkvmtkComputationalGeometryPython as vtkvmtkComputationalGeometry
        centerlineIdsArray = self._splitCenterlines.GetCellData().GetArray(centerlineIdsArrayName)
        centerlineIdsValueRange = centerlineIdsArray.GetValueRange()
        centerlineUtilities = vtkvmtkComputationalGeometry.vtkvmtkCenterlineUtilities()
        for centerlineId in range(centerlineIdsValueRange[0], (centerlineIdsValueRange[1] + 1)):
            centerlineCellIdsArray = vtk.vtkIdList()
            centerlineUtilities.GetCenterlineCellIds(self._splitCenterlines, centerlineIdsArrayName,
                                                     centerlineId, centerlineCellIdsArray)
            unitCellPolyDatas = self._createPolyData(centerlineCellIdsArray) # One per cell
            appendPolyData = vtk.vtkAppendPolyData() # We want a complete centerline
            for resultPolyData in unitCellPolyDatas:
                appendPolyData.AddInputData(resultPolyData)
            appendPolyData.Update() # The scalar arrays are rightly merged... fortunately.
            mergedCellsPolyData = self._mergeCenterlineCells(appendPolyData.GetOutput())
            centerlinePolyDatas.append(mergedCellsPolyData)

        stopTime = time.time()
        durationValue = '%.2f' % (stopTime-startTime)
        logging.info(_("Processing centerline ids completed in {duration} seconds").format(duration=durationValue))
        return centerlinePolyDatas

    def computeBifurcationVectors(self):
        """Compute the bifurcation reference systems and the bifurcation vectors of the centerline.
        This is the computation of the 'vmtkbifurcationreferencesystems' and 'vmtkbifurcationvectors'
        scripts of VMTK. For every branch that is adjacent to a bifurcation, the end of the branch group
        that is next to the bifurcation region is taken, and the branch is walked away from the
        bifurcation up to the center of the first maximum inscribed sphere that touches that end point.
        The bifurcation vector connects those two points, following the flow direction, therefore its
        length is of the order of the local vessel radius. Both ends are averages over the centerline
        tracts of the group, weighted by the square of the local radius.
        The result is cached until 'splitCenterlines()' is called again.
        :return: list of dicts, one for each bifurcation:
          {
            'bifurcationGroupId': the blanked group that represents the bifurcation,
            'position': origin of the bifurcation reference system, a radius weighted barycenter,
            'normal': normal of the bifurcation plane,
            'upNormal': direction from the parent branch towards the daughter branches,
            'branches': {groupId: {'groupId', 'role' ('Parent' or 'Child'), 'basePosition', 'vector',
                                   'outwardDirection', 'vectorLength', 'inPlaneAngleDegrees',
                                   'outOfPlaneAngleDegrees'}}
          }
          'outwardDirection' and the angles are given away from the bifurcation, which is the opposite of
          the stored vector for the parent branch. Angles are in degrees.
        """

        if self._bifurcationVectors is not None:
            return self._bifurcationVectors
        if not self._splitCenterlines:
            raise ValueError(_("Call 'splitCenterlines()' with an input centerline polydata first."))

        import time
        startTime = time.time()
        logging.info(_("Processing bifurcation vectors started"))

        import vtkvmtkComputationalGeometryPython as vtkvmtkComputationalGeometry

        referenceSystemsFilter = vtkvmtkComputationalGeometry.vtkvmtkCenterlineBifurcationReferenceSystems()
        referenceSystemsFilter.SetInputData(self._splitCenterlines)
        referenceSystemsFilter.SetRadiusArrayName(radiusArrayName)
        referenceSystemsFilter.SetGroupIdsArrayName(groupIdsArrayName)
        referenceSystemsFilter.SetBlankingArrayName(blankingArrayName)
        referenceSystemsFilter.SetNormalArrayName(normalArrayName)
        referenceSystemsFilter.SetUpNormalArrayName(upNormalArrayName)
        referenceSystemsFilter.Update()
        referenceSystems = referenceSystemsFilter.GetOutput()

        self._bifurcationVectors = []
        if (not referenceSystems) or (referenceSystems.GetNumberOfPoints() == 0):
            # The centerline does not have any bifurcation.
            return self._bifurcationVectors

        bifurcationVectorsFilter = vtkvmtkComputationalGeometry.vtkvmtkCenterlineBifurcationVectors()
        bifurcationVectorsFilter.SetInputData(self._splitCenterlines)
        bifurcationVectorsFilter.SetReferenceSystems(referenceSystems)
        bifurcationVectorsFilter.SetRadiusArrayName(radiusArrayName)
        bifurcationVectorsFilter.SetGroupIdsArrayName(groupIdsArrayName)
        bifurcationVectorsFilter.SetCenterlineIdsArrayName(centerlineIdsArrayName)
        bifurcationVectorsFilter.SetTractIdsArrayName(tractIdsArrayName)
        bifurcationVectorsFilter.SetBlankingArrayName(blankingArrayName)
        bifurcationVectorsFilter.SetReferenceSystemGroupIdsArrayName(groupIdsArrayName)
        bifurcationVectorsFilter.SetReferenceSystemNormalArrayName(normalArrayName)
        bifurcationVectorsFilter.SetReferenceSystemUpNormalArrayName(upNormalArrayName)
        bifurcationVectorsFilter.SetBifurcationVectorsArrayName(bifurcationVectorsArrayName)
        bifurcationVectorsFilter.SetInPlaneBifurcationVectorsArrayName(inPlaneBifurcationVectorsArrayName)
        bifurcationVectorsFilter.SetOutOfPlaneBifurcationVectorsArrayName(outOfPlaneBifurcationVectorsArrayName)
        bifurcationVectorsFilter.SetInPlaneBifurcationVectorAnglesArrayName(inPlaneBifurcationVectorAnglesArrayName)
        bifurcationVectorsFilter.SetOutOfPlaneBifurcationVectorAnglesArrayName(outOfPlaneBifurcationVectorAnglesArrayName)
        bifurcationVectorsFilter.SetBifurcationVectorsOrientationArrayName(bifurcationVectorsOrientationArrayName)
        bifurcationVectorsFilter.SetBifurcationGroupIdsArrayName(bifurcationGroupIdsArrayName)
        # The length of a vector tells over what distance the direction of a branch was determined.
        bifurcationVectorsFilter.SetNormalizeBifurcationVectors(0)
        bifurcationVectorsFilter.Update()
        bifurcationVectors = bifurcationVectorsFilter.GetOutput()
        if (not bifurcationVectors) or (bifurcationVectors.GetNumberOfPoints() == 0):
            return self._bifurcationVectors

        # One point of the reference systems for every bifurcation.
        bifurcationsByGroupId = {}
        referenceSystemPointData = referenceSystems.GetPointData()
        referenceSystemGroupIdsArray = referenceSystemPointData.GetArray(groupIdsArrayName)
        normalsArray = referenceSystemPointData.GetArray(normalArrayName)
        upNormalsArray = referenceSystemPointData.GetArray(upNormalArrayName)
        for pointId in range(referenceSystems.GetNumberOfPoints()):
            bifurcationGroupId = int(referenceSystemGroupIdsArray.GetTuple1(pointId))
            bifurcationsByGroupId[bifurcationGroupId] = {
                "bifurcationGroupId": bifurcationGroupId,
                "position": list(referenceSystems.GetPoint(pointId)),
                "normal": list(normalsArray.GetTuple3(pointId)) if normalsArray else [0.0, 0.0, 0.0],
                "upNormal": list(upNormalsArray.GetTuple3(pointId)) if upNormalsArray else [0.0, 0.0, 0.0],
                "branches": {},
                }

        # One point of the bifurcation vectors for every branch of every bifurcation.
        pointData = bifurcationVectors.GetPointData()
        groupIdsArray = pointData.GetArray(groupIdsArrayName)
        bifurcationGroupIdsArray = pointData.GetArray(bifurcationGroupIdsArrayName)
        orientationsArray = pointData.GetArray(bifurcationVectorsOrientationArrayName)
        vectorsArray = pointData.GetArray(bifurcationVectorsArrayName)
        inPlaneAnglesArray = pointData.GetArray(inPlaneBifurcationVectorAnglesArrayName)
        outOfPlaneAnglesArray = pointData.GetArray(outOfPlaneBifurcationVectorAnglesArrayName)
        if (not groupIdsArray) or (not bifurcationGroupIdsArray) or (not orientationsArray) or (not vectorsArray):
            raise ValueError(_("The bifurcation vectors are incomplete."))

        for pointId in range(bifurcationVectors.GetNumberOfPoints()):
            bifurcation = bifurcationsByGroupId.get(int(bifurcationGroupIdsArray.GetTuple1(pointId)))
            if bifurcation is None:
                continue
            # An upstream branch is the parent branch of the bifurcation.
            isUpstream = int(orientationsArray.GetTuple1(pointId)) == upstreamOrientation
            vector = list(vectorsArray.GetTuple3(pointId))
            vectorLength = vtk.vtkMath.Norm(vector)
            outwardDirection = [0.0, 0.0, 0.0]
            if vectorLength > minimumVectorLength:
                outwardDirection = [(-component if isUpstream else component) / vectorLength
                                    for component in vector]
            inPlaneAngleDegrees = math.degrees(inPlaneAnglesArray.GetTuple1(pointId)) if inPlaneAnglesArray else float("nan")
            outOfPlaneAngleDegrees = math.degrees(outOfPlaneAnglesArray.GetTuple1(pointId)) if outOfPlaneAnglesArray else float("nan")
            if isUpstream:
                inPlaneAngleDegrees = self.wrapAngleDegrees(inPlaneAngleDegrees + 180.0)
                outOfPlaneAngleDegrees = -outOfPlaneAngleDegrees
            groupId = int(groupIdsArray.GetTuple1(pointId))
            bifurcation["branches"][groupId] = {
                "groupId": groupId,
                "role": "Parent" if isUpstream else "Child",
                "basePosition": list(bifurcationVectors.GetPoint(pointId)),
                "vector": vector,
                "outwardDirection": outwardDirection,
                "vectorLength": vectorLength,
                "inPlaneAngleDegrees": inPlaneAngleDegrees,
                "outOfPlaneAngleDegrees": outOfPlaneAngleDegrees,
                }

        self._bifurcationVectors = [bifurcationsByGroupId[bifurcationGroupId]
                                    for bifurcationGroupId in sorted(bifurcationsByGroupId.keys())
                                    if bifurcationsByGroupId[bifurcationGroupId]["branches"]]

        stopTime = time.time()
        durationValue = '%.2f' % (stopTime-startTime)
        logging.info(_("Processing bifurcation vectors completed in {duration} seconds").format(duration=durationValue))
        return self._bifurcationVectors

    def processJunctionAngles(self):
        """Compute the angles between the branches that meet at each bifurcation.
        The direction of a branch is its bifurcation vector, oriented away from the bifurcation, so that
        the angle of a pair of branches is the angle between those two directions, in the [0, 180] range:
        180 degrees means that the two branches continue each other in a straight line. The angle
        projected onto the bifurcation plane and the angle of each branch with that plane are reported as
        well, as computed by VMTK. A bifurcation of degree n gives n*(n-1)/2 results, parent-child pairs
        first. A branch is identified by its GroupId, as the generated components are.
        :return: list of dicts, one for each pair of branches of each bifurcation
        """

        junctionAngles = []
        for bifurcation in self.computeBifurcationVectors():
            branches = [bifurcation["branches"][groupId] for groupId in sorted(bifurcation["branches"].keys())]
            # Parent branch first, so that a bifurcation gives parent-child, parent-child, child-child.
            branches.sort(key=lambda branch: (0 if branch["role"] == "Parent" else 1, branch["groupId"]))
            if len(branches) < 3:
                logging.warning(_("Skipping bifurcation {groupId}: it has {count} branches only.").format(
                                groupId=bifurcation["bifurcationGroupId"], count=len(branches)))
                continue
            for firstIndex in range(len(branches)):
                for secondIndex in range(firstIndex + 1, len(branches)):
                    branch1 = branches[firstIndex]
                    branch2 = branches[secondIndex]
                    junctionAngles.append({
                        "bifurcationGroupId": bifurcation["bifurcationGroupId"],
                        "junctionDegree": len(branches),
                        "junctionPosition": list(bifurcation["position"]),
                        "branch1GroupId": branch1["groupId"],
                        "branch2GroupId": branch2["groupId"],
                        "branch1Role": branch1["role"],
                        "branch2Role": branch2["role"],
                        "angleDegrees": self.angleDegrees(branch1["outwardDirection"], branch2["outwardDirection"]),
                        "inPlaneAngleDegrees": abs(self.wrapAngleDegrees(
                            branch1["inPlaneAngleDegrees"] - branch2["inPlaneAngleDegrees"])),
                        "branch1OutOfPlaneAngleDegrees": branch1["outOfPlaneAngleDegrees"],
                        "branch2OutOfPlaneAngleDegrees": branch2["outOfPlaneAngleDegrees"],
                        # End points of the measured directions, for showing the angle in 3D views.
                        "branch1Position": [bifurcation["position"][i] + branch1["outwardDirection"][i] * branch1["vectorLength"]
                                            for i in range(3)],
                        "branch2Position": [bifurcation["position"][i] + branch2["outwardDirection"][i] * branch2["vectorLength"]
                                            for i in range(3)],
                        })
        return junctionAngles

    def populateJunctionAnglesTable(self, tableNode, junctionAngles):
        """Write junction angle results in a table node, one row for each pair of branches."""

        if not tableNode:
            raise ValueError(_("Output table node is invalid"))

        tableNode.RemoveAllColumns()
        results = junctionAngles if junctionAngles else []
        numberOfRows = len(results)

        def integerColumn(columnName):
            column = vtk.vtkIntArray()
            column.SetName(columnName)
            column.SetNumberOfValues(numberOfRows)
            return column

        def doubleColumn(columnName):
            column = vtk.vtkDoubleArray()
            column.SetName(columnName)
            column.SetNumberOfValues(numberOfRows)
            return column

        def stringColumn(columnName):
            column = vtk.vtkStringArray()
            column.SetName(columnName)
            column.SetNumberOfValues(numberOfRows)
            return column

        bifurcationGroupIds = integerColumn("BifurcationGroupId")
        junctionDegrees = integerColumn("JunctionDegree")
        branch1GroupIds = integerColumn("Branch1GroupId")
        branch2GroupIds = integerColumn("Branch2GroupId")
        branch1Roles = stringColumn("Branch1Role")
        branch2Roles = stringColumn("Branch2Role")
        angles = doubleColumn("AngleDegrees")
        inPlaneAngles = doubleColumn("InPlaneAngleDegrees")
        branch1OutOfPlaneAngles = doubleColumn("Branch1OutOfPlaneAngleDegrees")
        branch2OutOfPlaneAngles = doubleColumn("Branch2OutOfPlaneAngleDegrees")

        junctionPositions = vtk.vtkDoubleArray()
        junctionPositions.SetName("JunctionPosition")
        junctionPositions.SetNumberOfComponents(3)
        junctionPositions.SetComponentName(0, "R")
        junctionPositions.SetComponentName(1, "A")
        junctionPositions.SetComponentName(2, "S")
        junctionPositions.SetNumberOfTuples(numberOfRows)

        for rowIndex in range(numberOfRows):
            junctionAngle = results[rowIndex]
            bifurcationGroupIds.SetValue(rowIndex, int(junctionAngle["bifurcationGroupId"]))
            junctionDegrees.SetValue(rowIndex, int(junctionAngle["junctionDegree"]))
            junctionPositions.SetTuple3(rowIndex, *junctionAngle["junctionPosition"])
            branch1GroupIds.SetValue(rowIndex, int(junctionAngle["branch1GroupId"]))
            branch2GroupIds.SetValue(rowIndex, int(junctionAngle["branch2GroupId"]))
            branch1Roles.SetValue(rowIndex, junctionAngle["branch1Role"])
            branch2Roles.SetValue(rowIndex, junctionAngle["branch2Role"])
            angles.SetValue(rowIndex, float(junctionAngle["angleDegrees"]))
            inPlaneAngles.SetValue(rowIndex, float(junctionAngle["inPlaneAngleDegrees"]))
            branch1OutOfPlaneAngles.SetValue(rowIndex, float(junctionAngle["branch1OutOfPlaneAngleDegrees"]))
            branch2OutOfPlaneAngles.SetValue(rowIndex, float(junctionAngle["branch2OutOfPlaneAngleDegrees"]))

        for column in [bifurcationGroupIds, junctionDegrees, junctionPositions,
                       branch1GroupIds, branch2GroupIds, branch1Roles, branch2Roles,
                       angles, inPlaneAngles, branch1OutOfPlaneAngles, branch2OutOfPlaneAngles]:
            tableNode.GetTable().AddColumn(column)

        tableNode.SetColumnUnitLabel("JunctionPosition", "mm")
        for column in [angles, inPlaneAngles, branch1OutOfPlaneAngles, branch2OutOfPlaneAngles]:
            tableNode.SetColumnUnitLabel(column.GetName(), "deg")
        tableNode.SetColumnDescription("BifurcationGroupId", _("GroupId of the bifurcation, as of its component"))
        tableNode.SetColumnDescription("Branch1GroupId", _("GroupId of the first branch of the pair"))
        tableNode.SetColumnDescription("Branch2GroupId", _("GroupId of the second branch of the pair"))
        tableNode.SetColumnDescription("AngleDegrees", _("Angle between the outward directions of the two"
                                                         " branches (180 degrees means that they continue"
                                                         " each other)"))
        tableNode.SetColumnDescription("InPlaneAngleDegrees", _("Angle of the pair projected onto the"
                                                                " bifurcation plane"))
        for columnName in ["Branch1OutOfPlaneAngleDegrees", "Branch2OutOfPlaneAngleDegrees"]:
            tableNode.SetColumnDescription(columnName, _("Angle between the branch and the bifurcation plane"))
        tableNode.GetTable().Modified()

    @staticmethod
    def junctionAnglePairType(branch1Role, branch2Role):
        """Type of a pair of branches: 'child-child', 'parent-child', or 'parent-parent'."""
        roles = [branch1Role, branch2Role]
        if roles == ["Child", "Child"]:
            return "child-child"
        if "Child" in roles:
            return "parent-child"
        return "parent-parent"

    @staticmethod
    def angleDegrees(vector1, vector2):
        """Angle between two vectors in degrees, in the [0, 180] range, nan for a vector of zero length."""
        norm1 = vtk.vtkMath.Norm(list(vector1))
        norm2 = vtk.vtkMath.Norm(list(vector2))
        if (norm1 <= 0.0) or (norm2 <= 0.0):
            return float("nan")
        # Clamp to compensate for numerical errors, acos fails outside [-1, 1].
        cosAngle = max(-1.0, min(1.0, vtk.vtkMath.Dot(list(vector1), list(vector2)) / (norm1 * norm2)))
        return math.degrees(math.acos(cosAngle))

    @staticmethod
    def wrapAngleDegrees(angleDegrees):
        """Wrap an angle to the (-180, 180] range."""
        if math.isnan(angleDegrees):
            return angleDegrees
        angleDegrees = math.fmod(angleDegrees, 360.0)
        if angleDegrees > 180.0:
            angleDegrees -= 360.0
        elif angleDegrees <= -180.0:
            angleDegrees += 360.0
        return angleDegrees

    def processGroupIds(self, bifurcations):
        """Split the centerline into blanked (bifurcation) or non-blanked (branch) groups.
        :return: list of (GroupId, polydata) pairs, one for every cell of every group
        """

        if not self._splitCenterlines:
            raise ValueError(_("Call 'splitCenterlines()' with an input centerline polydata first."))

        import time
        startTime = time.time()
        logging.info(_("Processing group ids started"))

        groupIdsPolyDatas = [] # One (GroupId, polydata) pair per cell
        groupIdsArray = vtk.vtkIdList()
        import vtkvmtkComputationalGeometryPython as vtkvmtkComputationalGeometry
        centerlineUtilities = vtkvmtkComputationalGeometry.vtkvmtkCenterlineUtilities()
        if (bifurcations):
            # Blanked
            centerlineUtilities.GetBlankedGroupsIdList(self._splitCenterlines, groupIdsArrayName,
                                                       blankingArrayName, groupIdsArray)
            for idx in range(groupIdsArray.GetNumberOfIds()):
                groupCellIdsArray = vtk.vtkIdList()
                groupCellId = groupIdsArray.GetId(idx)
                centerlineUtilities.GetGroupUniqueCellIds(self._splitCenterlines, groupIdsArrayName,
                                                          groupCellId, groupCellIdsArray)
                unitCellPolyDatas = self._createPolyData(groupCellIdsArray)
                for unitCellPolyData in unitCellPolyDatas:
                    groupIdsPolyDatas.append((groupCellId, unitCellPolyData))
        else:
            # Non-blanked
            centerlineUtilities.GetNonBlankedGroupsIdList(self._splitCenterlines, groupIdsArrayName,
                                                          blankingArrayName, groupIdsArray)
            for idx in range(groupIdsArray.GetNumberOfIds()):
                groupCellIdsArray = vtk.vtkIdList()
                groupCellId = groupIdsArray.GetId(idx)
                centerlineUtilities.GetGroupUniqueCellIds(self._splitCenterlines, groupIdsArrayName,
                                                          groupCellId, groupCellIdsArray)
                unitCellPolyDatas = self._createPolyData(groupCellIdsArray)
                for unitCellPolyData in unitCellPolyDatas:
                    groupIdsPolyDatas.append((groupCellId, unitCellPolyData))

        stopTime = time.time()
        durationValue = '%.2f' % (stopTime-startTime)
        logging.info(_("Processing group ids completed in {duration} seconds").format(duration=durationValue))
        return groupIdsPolyDatas
#
# CenterlineDisassemblyTest
#

class CenterlineDisassemblyTest(ScriptedLoadableModuleTest):

    def setUp(self):
        slicer.mrmlScene.Clear()

    def runTest(self):
        self.setUp()
        self.test_CenterlineDisassembly1()
        for test in [self.test_JunctionAngles, self.test_JunctionAnglesMultifurcation,
                     self.test_JunctionAnglesTable, self.test_JunctionAnglesOfAYShapedTube]:
            self.setUp()
            test()

    def test_CenterlineDisassembly1(self):
        self.delayDisplay(_("Starting the test"))

        self.delayDisplay(_("Test passed"))

    @staticmethod
    def branchDirection(angleDegrees):
        """Unit direction in the RA plane, measured from the +A axis."""
        return [math.sin(math.radians(angleDegrees)), math.cos(math.radians(angleDegrees)), 0.0]

    @staticmethod
    def createBifurcationVectors(childAngles = (30.0, -40.0), vectorLength = 4.0):
        """Bifurcation vectors of a bifurcation whose branches have known directions.
        The parent branch points in the +A direction, the children leave at the given angles from it.
        The format is the one of CenterlineDisassemblyLogic.computeBifurcationVectors().
        """
        branches = {
            0: {
                "groupId": 0,
                "role": "Parent",
                "basePosition": [0.0, -vectorLength, 0.0],
                # VMTK stores the vector of the parent branch along the flow, towards the bifurcation
                "vector": [0.0, vectorLength, 0.0],
                "outwardDirection": [0.0, -1.0, 0.0],
                "vectorLength": vectorLength,
                "inPlaneAngleDegrees": 180.0,
                "outOfPlaneAngleDegrees": 0.0,
                },
            }
        for childIndex in range(len(childAngles)):
            groupId = childIndex + 2
            outwardDirection = CenterlineDisassemblyTest.branchDirection(childAngles[childIndex])
            branches[groupId] = {
                "groupId": groupId,
                "role": "Child",
                "basePosition": [0.0, 0.0, 0.0],
                "vector": [component * vectorLength for component in outwardDirection],
                "outwardDirection": outwardDirection,
                "vectorLength": vectorLength,
                "inPlaneAngleDegrees": childAngles[childIndex],
                "outOfPlaneAngleDegrees": 0.0,
                }
        return [{
            "bifurcationGroupId": 1,
            "position": [0.0, 0.0, 0.0],
            "normal": [0.0, 0.0, 1.0],
            "upNormal": [0.0, 1.0, 0.0],
            "branches": branches,
            }]

    @staticmethod
    def anglesByGroupIdPair(junctionAngles):
        return {(junctionAngle["branch1GroupId"], junctionAngle["branch2GroupId"]): junctionAngle["angleDegrees"]
                for junctionAngle in junctionAngles}

    def test_JunctionAngles(self):
        """Angles of a bifurcation whose branches have known directions."""
        self.delayDisplay(_("Junction angles of a bifurcation"))

        logic = CenterlineDisassemblyLogic()
        logic._bifurcationVectors = self.createBifurcationVectors()
        junctionAngles = logic.processJunctionAngles()

        # A bifurcation gives three pairs of branches, the parent-child pairs first
        self.assertEqual(len(junctionAngles), 3)
        self.assertEqual([(junctionAngle["branch1GroupId"], junctionAngle["branch2GroupId"])
                          for junctionAngle in junctionAngles], [(0, 2), (0, 3), (2, 3)])
        self.assertEqual([(junctionAngle["branch1Role"], junctionAngle["branch2Role"])
                          for junctionAngle in junctionAngles],
                         [("Parent", "Child"), ("Parent", "Child"), ("Child", "Child")])
        for junctionAngle in junctionAngles:
            self.assertEqual(junctionAngle["bifurcationGroupId"], 1)
            self.assertEqual(junctionAngle["junctionDegree"], 3)

        angles = self.anglesByGroupIdPair(junctionAngles)
        self.assertAlmostEqual(angles[(0, 2)], 150.0, delta=0.01)
        self.assertAlmostEqual(angles[(0, 3)], 140.0, delta=0.01)
        self.assertAlmostEqual(angles[(2, 3)], 70.0, delta=0.01)

        # The branches of this bifurcation are in one plane, so the in-plane angle is the same
        for junctionAngle in junctionAngles:
            self.assertAlmostEqual(junctionAngle["inPlaneAngleDegrees"], junctionAngle["angleDegrees"], delta=0.01)

        # The pair types drive the color and the name of the annotations
        self.assertEqual(logic.junctionAnglePairType("Parent", "Child"), "parent-child")
        self.assertEqual(logic.junctionAnglePairType("Child", "Child"), "child-child")
        # A direction cannot be determined from a vector of zero length
        self.assertTrue(math.isnan(logic.angleDegrees([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])))

        self.delayDisplay(_("Test passed"))

    def test_JunctionAnglesMultifurcation(self):
        """A junction of degree n must give n*(n-1)/2 pairs of branches."""
        self.delayDisplay(_("Junction angles of a multifurcation"))

        logic = CenterlineDisassemblyLogic()
        logic._bifurcationVectors = self.createBifurcationVectors(childAngles = (45.0, 0.0, -45.0))
        junctionAngles = logic.processJunctionAngles()

        self.assertEqual(len(junctionAngles), 6)
        for junctionAngle in junctionAngles:
            self.assertEqual(junctionAngle["junctionDegree"], 4)
        pairTypes = [logic.junctionAnglePairType(junctionAngle["branch1Role"], junctionAngle["branch2Role"])
                     for junctionAngle in junctionAngles]
        self.assertEqual(pairTypes.count("parent-child"), 3)
        self.assertEqual(pairTypes.count("child-child"), 3)

        angles = self.anglesByGroupIdPair(junctionAngles)
        self.assertAlmostEqual(angles[(0, 2)], 135.0, delta=0.01)
        self.assertAlmostEqual(angles[(0, 3)], 180.0, delta=0.01)
        self.assertAlmostEqual(angles[(0, 4)], 135.0, delta=0.01)
        self.assertAlmostEqual(angles[(2, 3)], 45.0, delta=0.01)
        self.assertAlmostEqual(angles[(2, 4)], 90.0, delta=0.01)
        self.assertAlmostEqual(angles[(3, 4)], 45.0, delta=0.01)

        self.delayDisplay(_("Test passed"))

    def test_JunctionAnglesTable(self):
        """The results table must contain the results."""
        self.delayDisplay(_("Junction angles table"))

        logic = CenterlineDisassemblyLogic()
        logic._bifurcationVectors = self.createBifurcationVectors()
        junctionAngles = logic.processJunctionAngles()
        tableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "Junction angles")
        logic.populateJunctionAnglesTable(tableNode, junctionAngles)

        table = tableNode.GetTable()
        self.assertEqual(table.GetNumberOfRows(), 3)
        self.assertEqual([table.GetColumnName(columnIndex) for columnIndex in range(table.GetNumberOfColumns())],
                         ["BifurcationGroupId", "JunctionDegree", "JunctionPosition",
                          "Branch1GroupId", "Branch2GroupId", "Branch1Role", "Branch2Role",
                          "AngleDegrees", "InPlaneAngleDegrees",
                          "Branch1OutOfPlaneAngleDegrees", "Branch2OutOfPlaneAngleDegrees"])
        self.assertEqual(table.GetColumnByName("JunctionPosition").GetNumberOfComponents(), 3)
        for rowIndex in range(table.GetNumberOfRows()):
            junctionAngle = junctionAngles[rowIndex]
            self.assertEqual(table.GetValueByName(rowIndex, "BifurcationGroupId").ToInt(),
                             junctionAngle["bifurcationGroupId"])
            self.assertEqual(table.GetValueByName(rowIndex, "Branch1GroupId").ToInt(), junctionAngle["branch1GroupId"])
            self.assertEqual(table.GetValueByName(rowIndex, "Branch2GroupId").ToInt(), junctionAngle["branch2GroupId"])
            self.assertEqual(table.GetValueByName(rowIndex, "Branch1Role").ToString(), junctionAngle["branch1Role"])
            self.assertAlmostEqual(table.GetValueByName(rowIndex, "AngleDegrees").ToDouble(),
                                   junctionAngle["angleDegrees"], places=9)

        # An empty result must clear the table
        logic.populateJunctionAnglesTable(tableNode, [])
        self.assertEqual(tableNode.GetTable().GetNumberOfRows(), 0)

        self.delayDisplay(_("Test passed"))

    @staticmethod
    def createTubeSurface(segments, spacing = 0.8, margin = 12.0):
        """Closed surface of a set of tubes, each segment given as (startPosition, endPosition, radius)."""
        import numpy as np
        from vtk.util import numpy_support

        def distanceToSegment(points, startPosition, endPosition):
            segmentVector = endPosition - startPosition
            ratios = np.clip(((points - startPosition) @ segmentVector) / (segmentVector @ segmentVector), 0.0, 1.0)
            return np.linalg.norm(points - (startPosition + ratios[:, None] * segmentVector), axis=1)

        segments = [(np.array(startPosition, dtype=float), np.array(endPosition, dtype=float), radius)
                    for startPosition, endPosition, radius in segments]
        endPositions = np.array([position for segment in segments for position in segment[:2]])
        maximumRadius = max(segment[2] for segment in segments)
        lowerBound = endPositions.min(axis=0) - maximumRadius - margin
        upperBound = endPositions.max(axis=0) + maximumRadius + margin
        dimensions = [int((upperBound[i] - lowerBound[i]) / spacing) for i in range(3)]
        grid = np.stack(np.meshgrid(*[lowerBound[i] + spacing * np.arange(dimensions[i]) for i in range(3)],
                                    indexing="ij"), axis=-1).reshape(-1, 3)
        values = np.full(grid.shape[0], 1e9)
        for startPosition, endPosition, radius in segments:
            values = np.minimum(values, distanceToSegment(grid, startPosition, endPosition) - radius)
        values = values.astype(np.float32).reshape(dimensions).transpose(2, 1, 0).ravel()

        imageData = vtk.vtkImageData()
        imageData.SetDimensions(*dimensions)
        imageData.SetOrigin(*lowerBound)
        imageData.SetSpacing(spacing, spacing, spacing)
        scalars = numpy_support.numpy_to_vtk(values, deep=True)
        scalars.SetName("Distance")
        imageData.GetPointData().SetScalars(scalars)
        marchingCubes = vtk.vtkMarchingCubes()
        marchingCubes.SetInputData(imageData)
        marchingCubes.SetValue(0, 0.0)
        smoother = vtk.vtkWindowedSincPolyDataFilter()
        smoother.SetInputConnection(marchingCubes.GetOutputPort())
        smoother.SetNumberOfIterations(20)
        smoother.NormalizeCoordinatesOn()
        smoother.Update()
        return smoother.GetOutput()

    def test_JunctionAnglesOfAYShapedTube(self):
        """The angles of a Y shaped tube must match the angles of the axes of the tubes."""
        self.delayDisplay(_("Junction angles of a Y shaped tube"))

        vesselRadius = 4.0
        junctionPosition = [0.0, 0.0, 0.0]
        inletPosition = [0.0, -40.0, 0.0]
        childEndPositions = [[component * 40.0 for component in self.branchDirection(angleDegrees)]
                             for angleDegrees in (30.0, -40.0)]
        surfacePolyData = self.createTubeSurface(
            [(inletPosition, junctionPosition, vesselRadius)]
            + [(junctionPosition, childEndPosition, vesselRadius) for childEndPosition in childEndPositions])

        # The input of this module is a centerline model of the 'Extract centerline' module
        import ExtractCenterline
        extractCenterlineLogic = ExtractCenterline.ExtractCenterlineLogic()
        endPointsMarkupsNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "Endpoints")
        endPointsMarkupsNode.AddControlPoint(vtk.vtkVector3d(inletPosition))
        for childEndPosition in childEndPositions:
            endPointsMarkupsNode.AddControlPoint(vtk.vtkVector3d(childEndPosition))
        # The inlet is the unselected control point, it gives the flow direction
        endPointsMarkupsNode.SetNthControlPointSelected(0, False)
        preprocessedPolyData = extractCenterlineLogic.preprocess(surfacePolyData, 8000, 4.0, False)
        centerlinePolyData = extractCenterlineLogic.extractCenterline(preprocessedPolyData,
                                                                      endPointsMarkupsNode, 1.0)[0]

        logic = CenterlineDisassemblyLogic()
        logic.splitCenterlines(centerlinePolyData)
        junctionAngles = logic.processJunctionAngles()

        self.assertEqual(len(junctionAngles), 3)
        self.assertEqual([(junctionAngle["branch1Role"], junctionAngle["branch2Role"])
                          for junctionAngle in junctionAngles],
                         [("Parent", "Child"), ("Parent", "Child"), ("Child", "Child")])

        # The bifurcation vectors follow each branch through the bifurcation, so the measured angles are
        # close to the angles of the axes of the tubes
        angles = self.anglesByGroupIdPair(junctionAngles)
        self.assertAlmostEqual(angles[(0, 2)], 150.0, delta=5.0)
        self.assertAlmostEqual(angles[(0, 3)], 140.0, delta=5.0)
        self.assertAlmostEqual(angles[(2, 3)], 70.0, delta=5.0)

        # The direction of a branch is determined over a distance of the order of the local vessel radius
        for bifurcation in logic.computeBifurcationVectors():
            for branch in bifurcation["branches"].values():
                self.assertAlmostEqual(branch["vectorLength"], vesselRadius, delta=0.5 * vesselRadius)

        # The branches are the non-blanked groups, they are also generated as separate components
        branchGroupIds = set(groupId for groupId, polyData in logic.processGroupIds(False))
        for junctionAngle in junctionAngles:
            self.assertIn(junctionAngle["branch1GroupId"], branchGroupIds)
            self.assertIn(junctionAngle["branch2GroupId"], branchGroupIds)
        self.assertIn(junctionAngles[0]["bifurcationGroupId"],
                      set(groupId for groupId, polyData in logic.processGroupIds(True)))

        self.delayDisplay(_("Test passed"))


BIFURCATIONS_ITEM_ID = 1
BRANCHES_ITEM_ID = 2
CENTERLINES_ITEM_ID = 3
JUNCTION_ANGLES_ITEM_ID = 4

blankingArrayName = 'Blanking'
radiusArrayName = 'Radius'  # maximum inscribed sphere radius
groupIdsArrayName = 'GroupIds'
centerlineIdsArrayName = 'CenterlineIds'
tractIdsArrayName = 'TractIds'
edgeArrayName = 'EdgeArray'
edgePCoordArrayName = 'EdgePCoordArray'
# Bifurcation reference systems and bifurcation vectors
normalArrayName = 'Normal'
upNormalArrayName = 'UpNormal'
bifurcationVectorsArrayName = 'BifurcationVectors'
inPlaneBifurcationVectorsArrayName = 'InPlaneBifurcationVectors'
outOfPlaneBifurcationVectorsArrayName = 'OutOfPlaneBifurcationVectors'
inPlaneBifurcationVectorAnglesArrayName = 'InPlaneBifurcationVectorAngles'
outOfPlaneBifurcationVectorAnglesArrayName = 'OutOfPlaneBifurcationVectorAngles'
bifurcationVectorsOrientationArrayName = 'BifurcationVectorsOrientation'
bifurcationGroupIdsArrayName = 'BifurcationGroupIds'
# A branch that is upstream of a bifurcation is its parent branch
upstreamOrientation = 0
# Vectors shorter than this, in mm, do not give a direction
minimumVectorLength = 1e-6

ROLE_INPUT_CENTERLINE = "InputCenterline"
ROLE_CREATE_MODELS = "CreateModels"
ROLE_CREATE_CURVES = "CreateCurves"
ROLE_SHOW_CURVE_NAMES = "ShowCurveNames"
ROLE_CREATE_BIFURCATIONS = "CreateBifurcations"
ROLE_CREATE_BRANCHES = "CreateBranches"
ROLE_CREATE_CENTERLINES = "CreateCenterlines"
ROLE_CREATE_JUNCTION_ANGLES = "CreateJunctionAngles"
