// Stark World Engine Runtime - world objects (see StarkWorldActors.h).
// UBoxComponent: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/Components/UBoxComponent
// UPointLightComponent: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/Components/UPointLightComponent
// UMaterialInstanceDynamic: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/Materials/UMaterialInstanceDynamic
#include "StarkWorldActors.h"
#include "StarkGameSubsystem.h"
#include "StarkRules.h"
#include "StarkCharacter.h"
#include "StarkEnemy.h"
#include "Components/BoxComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/GameInstance.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "UObject/ConstructorHelpers.h"

static UStarkGameSubsystem* StarkSubW(const UObject* Ctx)
{
	const UWorld* W = Ctx ? Ctx->GetWorld() : nullptr;
	UGameInstance* GI = W ? W->GetGameInstance() : nullptr;
	return GI ? GI->GetSubsystem<UStarkGameSubsystem>() : nullptr;
}

static void Tint(UStaticMeshComponent* C, const FLinearColor& Col, UObject* Outer)
{
	if (UMaterialInterface* Base = C ? C->GetMaterial(0) : nullptr)
	{
		if (UMaterialInstanceDynamic* Mid = UMaterialInstanceDynamic::Create(Base, Outer))
		{
			Mid->SetVectorParameterValue(TEXT("Color"), Col);
			C->SetMaterial(0, Mid);
		}
	}
}

static void Shape(UStaticMeshComponent* C, UStaticMesh* M, const FVector& Loc, const FVector& Scale)
{
	C->SetStaticMesh(M);
	C->SetRelativeLocation(Loc);
	C->SetRelativeScale3D(Scale);
	C->SetVisibility(M != nullptr);
}

AStarkInteractable::AStarkInteractable()
{
	PrimaryActorTick.bCanEverTick = true;
	static ConstructorHelpers::FObjectFinder<UStaticMesh> Cube(TEXT("/Engine/BasicShapes/Cube.Cube"));
	static ConstructorHelpers::FObjectFinder<UStaticMesh> Sphere(TEXT("/Engine/BasicShapes/Sphere.Sphere"));
	static ConstructorHelpers::FObjectFinder<UStaticMesh> Cylinder(TEXT("/Engine/BasicShapes/Cylinder.Cylinder"));
	static ConstructorHelpers::FObjectFinder<UStaticMesh> Cone(TEXT("/Engine/BasicShapes/Cone.Cone"));
	ProxyCube = Cube.Object;
	ProxySphere = Sphere.Object;
	ProxyCylinder = Cylinder.Object;
	ProxyCone = Cone.Object;
	Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	RootComponent = Root;
	MeshA = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("MeshA"));
	MeshB = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("MeshB"));
	MeshC = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("MeshC"));
	for (UStaticMeshComponent* C : { MeshA.Get(), MeshB.Get(), MeshC.Get() })
	{
		C->SetupAttachment(Root);
		C->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	}
	Blocker = CreateDefaultSubobject<UBoxComponent>(TEXT("Blocker"));
	Blocker->SetupAttachment(Root);
	Blocker->SetCollisionProfileName(TEXT("BlockAll"));
	Glow = CreateDefaultSubobject<UPointLightComponent>(TEXT("Glow"));
	Glow->SetupAttachment(Root);
	Glow->SetRelativeLocation(FVector(0.f, 0.f, 120.f));
	Glow->SetIntensity(0.f);
	Glow->SetAttenuationRadius(700.f);
	Glow->SetCastShadows(false);
}

FString AStarkInteractable::GetGoneKey() const
{
	if (!GoneKeyOverride.IsEmpty()) { return GoneKeyOverride; }
	UStarkGameSubsystem* G = StarkSubW(this);
	return (G && ObjectIndex >= 0) ? G->GoneKey(ObjectIndex) : FString();
}

void AStarkInteractable::OnConstruction(const FTransform& Transform)
{
	Super::OnConstruction(Transform);
	SetupVisuals();
}

void AStarkInteractable::SetupVisuals()
{
	const bool bArt = ArtMesh != nullptr;
	UStaticMesh* GCube = ProxyCube;
	UStaticMesh* GSphere = ProxySphere;
	UStaticMesh* GCylinder = ProxyCylinder;
	UStaticMesh* GCone = ProxyCone;
	Shape(MeshA, nullptr, FVector::ZeroVector, FVector::OneVector);
	Shape(MeshB, nullptr, FVector::ZeroVector, FVector::OneVector);
	Shape(MeshC, nullptr, FVector::ZeroVector, FVector::OneVector);
	Blocker->SetBoxExtent(FVector(1.f), false);
	Blocker->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	// Basic shapes are 100 cm; plan local x maps to UE local Y and plan local z to UE local X (see StarkTypes.h).
	switch (Kind)
	{
	case EStarkThing::Crystal:
		Shape(MeshA, bArt ? ArtMesh.Get() : GCone, FVector(0, 0, 75), bArt ? FVector(ArtScale) : FVector(0.45f, 0.45f, 1.5f));
		if (!bArt) { Shape(MeshB, GCone, FVector(15, 35, 40), FVector(0.3f, 0.3f, 0.9f)); }
		Glow->SetIntensity(800.f);
		Glow->SetLightColor(Color);
		break;
	case EStarkThing::Item:
		Shape(MeshA, bArt ? ArtMesh.Get() : GSphere, FVector(0, 0, 70), bArt ? FVector(ArtScale) : FVector(0.4f, 0.4f, 0.55f));
		break;
	case EStarkThing::Chest:
		Shape(MeshA, bArt ? ArtMesh.Get() : GCube, FVector(0, 0, 28), bArt ? FVector(ArtScale) : FVector(0.6f, 0.9f, 0.55f));
		if (!bArt) { Shape(MeshB, GCube, FVector(0, 0, 56), FVector(0.65f, 0.95f, 0.14f)); }
		Blocker->SetBoxExtent(FVector(32.f, 48.f, 30.f), false);
		Blocker->SetRelativeLocation(FVector(0, 0, 30));
		Blocker->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);
		break;
	case EStarkThing::Door:
		Shape(MeshA, bArt ? ArtMesh.Get() : GCube, FVector(0, 0, 140), bArt ? FVector(ArtScale) : FVector(0.3f, 2.6f, 2.8f));
		if (!bArt) { Shape(MeshB, GCube, FVector(0, -160, 150), FVector(0.7f, 0.6f, 3.f)); Shape(MeshC, GCube, FVector(0, 160, 150), FVector(0.7f, 0.6f, 3.f)); }
		Blocker->SetBoxExtent(FVector(50.f, 190.f, 150.f), false);
		Blocker->SetRelativeLocation(FVector(0, 0, 150));
		Blocker->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);
		break;
	case EStarkThing::Portal:
	case EStarkThing::Exit:
		Shape(MeshA, bArt ? ArtMesh.Get() : GCube, FVector(0, 0, 195), bArt ? FVector(ArtScale) : FVector(0.06f, 2.6f, 3.8f));
		if (!bArt) { Shape(MeshB, GCube, FVector(0, -160, 200), FVector(0.6f, 0.6f, 4.f)); Shape(MeshC, GCube, FVector(0, 160, 200), FVector(0.6f, 0.6f, 4.f)); }
		Glow->SetIntensity(2500.f);
		Glow->SetLightColor(FLinearColor(0.7f, 0.6f, 1.f));
		break;
	case EStarkThing::Checkpoint:
		Shape(MeshA, bArt ? ArtMesh.Get() : GCylinder, FVector(0, 0, 130), bArt ? FVector(ArtScale) : FVector(0.1f, 0.1f, 2.6f));
		if (!bArt) { Shape(MeshB, GCube, FVector(0, 48, 225), FVector(0.04f, 0.9f, 0.55f)); }
		break;
	case EStarkThing::Hazard:
		Shape(MeshA, bArt ? ArtMesh.Get() : GCone, FVector(0, 0, 50), bArt ? FVector(ArtScale) : FVector(1.8f, 1.8f, 1.f));
		break;
	}
}

void AStarkInteractable::BeginPlay()
{
	Super::BeginPlay();
	UStarkGameSubsystem* G = StarkSubW(this);
	if (!G) { return; }
	const bool bGone = G->IsGone(GetGoneKey());
	if (bGone && (Kind == EStarkThing::Item || Kind == EStarkThing::Crystal)) { Destroy(); return; }
	bOpened = bGone && (Kind == EStarkThing::Chest || Kind == EStarkThing::Door);
	if (Kind == EStarkThing::Item && G->Rules) { Color = G->Rules->GetItem(Item).Color; }
	RefreshVisuals();
	if (bOpened && Kind == EStarkThing::Door) { MeshA->SetVisibility(false); Blocker->SetCollisionEnabled(ECollisionEnabled::NoCollision); }
	G->RegisterInteractable(this);
}

void AStarkInteractable::RefreshVisuals()
{
	SetupVisuals();
	if (ArtMesh) { return; }
	if (Kind == EStarkThing::Item || Kind == EStarkThing::Crystal) { Tint(MeshA, Color, this); Tint(MeshB, Color, this); }
	if (Kind == EStarkThing::Chest) { Tint(MeshA, FLinearColor(0.21f, 0.07f, 0.02f), this); Tint(MeshB, FLinearColor(0.89f, 0.52f, 0.05f), this); }
	if (Kind == EStarkThing::Door) { Tint(MeshA, FLinearColor(0.1f, 0.04f, 0.01f), this); }
	if (Kind == EStarkThing::Portal || Kind == EStarkThing::Exit) { Tint(MeshA, FLinearColor(0.35f, 0.25f, 1.f), this); }
	if (Kind == EStarkThing::Hazard) { Tint(MeshA, FLinearColor(0.7f, 0.03f, 0.03f), this); }
}

void AStarkInteractable::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	if (UStarkGameSubsystem* G = StarkSubW(this)) { G->UnregisterInteractable(this); }
	Super::EndPlay(EndPlayReason);
}

bool AStarkInteractable::CanInteract() const
{
	return (Kind == EStarkThing::Chest || Kind == EStarkThing::Door) && !bOpened;
}

FString AStarkInteractable::PromptText() const
{
	return Kind == EStarkThing::Door ? TEXT("Unlock door") : TEXT("Open chest");
}

int32 AStarkInteractable::Destination() const
{
	UStarkGameSubsystem* G = StarkSubW(this);
	return Target >= 0 ? Target : (G ? G->GetLevelIndex() + 1 : 0);
}

bool AStarkInteractable::IsLocked() const
{
	UStarkGameSubsystem* G = StarkSubW(this);
	if (LockQuest.IsEmpty() || !G || !G->Rules || !G->Rules->FindQuest(LockQuest)) { return false; }
	return G->Rules->QuestState(LockQuest) != TEXT("done");
}

void AStarkInteractable::Interact(AActor* By)
{
	UStarkGameSubsystem* G = StarkSubW(this);
	if (!G || !G->Rules || bOpened) { return; }
	if (Kind == EStarkThing::Chest)
	{
		bOpened = true;
		G->MarkGone(GetGoneKey());
		G->PlaySfx(TEXT("coin"));
		if (!Item.IsEmpty()) { G->Rules->Give(Item, FMath::Max(1, Count)); }
		if (Gold > 0) { G->Rules->Gold += Gold; G->Rules->Toast(FString::Printf(TEXT("+%d gold"), Gold)); }
		if (Item.IsEmpty() && Gold <= 0) { G->Rules->Gold += 10; G->Rules->Toast(TEXT("+10 gold")); }
		MeshB->SetRelativeRotation(FRotator(0.f, 0.f, -60.f));
		G->Changed();
	}
	else if (Kind == EStarkThing::Door)
	{
		const FStarkItemDef Key = G->Rules->GetItem(KeyItem);
		if (G->Rules->Has(KeyItem))
		{
			if (Key.Kind == TEXT("key")) { G->Rules->Take(KeyItem, 1); }
			bOpened = true;
			G->MarkGone(GetGoneKey());
			G->PlaySfx(TEXT("door"));
			G->Rules->Toast(TEXT("Unlocked with ") + Key.Name);
			MeshA->SetVisibility(false);
			Blocker->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		}
		else
		{
			G->Rules->Toast(TEXT("Locked. You need: ") + Key.Name);
			G->PlaySfx(TEXT("hit"));
		}
		G->Changed();
	}
}

void AStarkInteractable::Touch()
{
	UStarkGameSubsystem* G = StarkSubW(this);
	AStarkPlayerCharacter* Pl = G ? G->GetPlayer() : nullptr;
	if (!G || !G->Rules || !Pl) { return; }
	switch (Kind)
	{
	case EStarkThing::Item:
	case EStarkThing::Crystal:
	{
		if (bTaken) { return; }
		bTaken = true;
		G->MarkGone(GetGoneKey());
		G->PlaySfx(TEXT("coin"));
		if (Kind == EStarkThing::Crystal)
		{
			G->Rules->Score += 10;
			G->Rules->Give(TEXT("crystal"), 1, true);
			int32 Total = 0, Got = 0;
			if (const FStarkLevelDef* L = G->Rules->FindLevel(G->GetLevelIndex()))
			{
				for (const FStarkObjectDef& O : L->Objects)
				{
					if (O.Type == TEXT("crystal")) { ++Total; if (G->IsGone(G->GoneKey(O.Index))) { ++Got; } }
				}
			}
			if (Total > 0) { G->Rules->Toast(FString::Printf(TEXT("Crystal %d/%d"), Got, Total)); }
			if (G->Rules->Def.Quests.Num() == 0 && Total > 0 && Got >= Total && !G->Rules->bWon)
			{
				G->Rules->bWon = true;
				if (G->Rules->OnWin) { G->Rules->OnWin(); }
			}
		}
		else
		{
			G->Rules->Give(Item.IsEmpty() ? FString(TEXT("potion")) : Item, FMath::Max(1, Count));
		}
		G->Changed();
		Destroy();
		return;
	}
	case EStarkThing::Checkpoint:
	{
		G->SetCheckpoint(Pl->GetPlanXZ());
		return;
	}
	case EStarkThing::Hazard:
	{
		Pl->HurtPlayer(1.f);
		return;
	}
	case EStarkThing::Portal:
	case EStarkThing::Exit:
	{
		if (G->bPorting) { return; }
		if (IsLocked())
		{
			if (!bWarned)
			{
				bWarned = true;
				const FStarkQuestDef* Q = G->Rules->FindQuest(LockQuest);
				G->Rules->Toast(FString::Printf(TEXT("Sealed. Finish \"%s\" first."), Q ? *Q->Title : *LockQuest));
				G->Changed();
			}
			return;
		}
		const int32 To = Destination();
		if (To < 0 || To >= G->GetLevelCount())
		{
			if (Kind == EStarkThing::Exit && !G->Rules->bWon)
			{
				if (G->Rules->ActiveQuests().Num() > 0 && G->Rules->Def.Quests.Num() > 0)
				{
					if (!bWarned) { bWarned = true; G->Rules->Toast(TEXT("Finish your quests first!")); G->Changed(); }
					return;
				}
				G->Rules->bWon = true;
				if (G->Rules->OnWin) { G->Rules->OnWin(); }
				G->Changed();
				return;
			}
			if (!bWarned) { bWarned = true; G->Rules->Toast(TEXT("This portal leads nowhere yet.")); G->Changed(); }
			return;
		}
		const FVector2D P = Pl->GetPlanXZ();
		FStarkEvent E;
		E.X = P.X;
		E.Z = P.Y;
		G->Rules->Event(TEXT("reach"), E);
		G->TravelToLevel(To);
		return;
	}
	default:
		return;
	}
}

void AStarkInteractable::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	Age += DeltaSeconds;
	if (Kind == EStarkThing::Item || Kind == EStarkThing::Crystal)
	{
		MeshA->SetRelativeRotation(FRotator(0.f, Age * 90.f, 0.f));
	}
	UStarkGameSubsystem* G = StarkSubW(this);
	AStarkPlayerCharacter* Pl = G ? G->GetPlayer() : nullptr;
	if (!Pl || Kind == EStarkThing::Chest || Kind == EStarkThing::Door) { return; }
	const FVector D = Pl->GetActorLocation() - GetActorLocation();
	const float Radius = Kind == EStarkThing::Checkpoint ? 160.f : (Kind == EStarkThing::Crystal ? 140.f : TriggerRadius);
	const bool bInside = Pl->bSideView ? (FMath::Abs(D.X) < Radius && FMath::Abs(D.Z) < 200.f) : (D.Size2D() < Radius && FMath::Abs(D.Z) < 300.f);
	if (!bInside)
	{
		if (D.Size2D() > 250.f) { bWarned = false; }
		return;
	}
	Touch();
}

// ---------------------------------------------------------------- projectiles
AStarkProjectile::AStarkProjectile()
{
	PrimaryActorTick.bCanEverTick = true;
	static ConstructorHelpers::FObjectFinder<UStaticMesh> Sphere(TEXT("/Engine/BasicShapes/Sphere.Sphere"));
	Mesh = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Mesh"));
	RootComponent = Mesh;
	Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Mesh->SetRelativeScale3D(FVector(0.35f));
	if (Sphere.Succeeded()) { Mesh->SetStaticMesh(Sphere.Object); }
}

void AStarkProjectile::BeginPlay()
{
	Super::BeginPlay();
	Tint(Mesh, Color, this);
}

void AStarkProjectile::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	Life -= DeltaSeconds;
	SetActorLocation(GetActorLocation() + Velocity * DeltaSeconds);
	UStarkGameSubsystem* G = StarkSubW(this);
	if (!G || Life <= 0.f) { Destroy(); return; }
	const FVector P = GetActorLocation();
	if (!G->IsSideView())
	{
		const FVector2D Xz = UEToStarkXZ(P);
		if (G->TerrainHeightAt(Xz.X, Xz.Y) * 100.f > P.Z) { Destroy(); return; }
	}
	if (bFromEnemy)
	{
		AStarkPlayerCharacter* Pl = G->GetPlayer();
		if (Pl && FVector::Dist2D(Pl->GetActorLocation(), P) < 70.f && FMath::Abs(P.Z - Pl->GetActorLocation().Z) < 120.f)
		{
			Pl->HurtPlayer(Damage);
			Destroy();
		}
		return;
	}
	for (AStarkEnemyCharacter* E : G->Enemies())
	{
		const float R = 80.f * E->SizeScale + (E->IsBoss() ? 120.f : 0.f);
		if (FVector::Dist2D(E->GetActorLocation(), P) < R)
		{
			E->TakeHit(Damage, Velocity.GetSafeNormal());
			Destroy();
			return;
		}
	}
}
