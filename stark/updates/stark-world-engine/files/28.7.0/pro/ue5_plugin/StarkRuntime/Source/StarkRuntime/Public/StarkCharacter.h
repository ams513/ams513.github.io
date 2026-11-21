// Stark World Engine Runtime - the hero. Third-person (3D levels) or side view (2.5D chapters). Keys are read directly from the
// PlayerController so no Input Mapping assets are needed: WASD/arrows move, Space jump, J or left mouse attack,
// E talk/open/unlock, 1-4 answers, H potion, Shift dash, K whirl, F bolt, Z/C or right mouse drag camera,
// L quests, I bag, Esc menu (save 1-3 / load).
// ACharacter: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/GameFramework/ACharacter
// USpringArmComponent: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/GameFramework/USpringArmComponent
// APlayerController::WasInputKeyJustPressed: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/GameFramework/APlayerController/WasInputKeyJustPressed
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "StarkCharacter.generated.h"

class USpringArmComponent;
class UCameraComponent;
class UStaticMeshComponent;
class UChildActorComponent;

UCLASS()
class STARKRUNTIME_API AStarkPlayerCharacter : public ACharacter
{
	GENERATED_BODY()
public:
	AStarkPlayerCharacter();
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Stark World Engine") TObjectPtr<USpringArmComponent> CameraBoom;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Stark World Engine") TObjectPtr<UCameraComponent> FollowCamera;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Stark World Engine") TObjectPtr<UStaticMeshComponent> BodyMesh;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Stark World Engine") TObjectPtr<UStaticMeshComponent> HeadMesh;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Stark World Engine|Art") TObjectPtr<UChildActorComponent> Visual;
	/** MetaHuman-ready slot for the hero: a character Blueprint shown instead of the proxy body. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine|Art") TSubclassOf<AActor> VisualClass;

	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void Attack();
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void Interact();
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void Dash();
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void Whirl();
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void Bolt();
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void HurtPlayer(float Damage);
	/** Respawn at the checkpoint (plan x, z) when bAtPoint, else at the level start. */
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void Respawn(bool bAtPoint, FVector2D PlanXZ);
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void TeleportToPlan(float PlanX, float PlanZ);
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") FVector2D GetPlanXZ() const;
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") FVector FacingVector() const;
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") AActor* NearestInteractable(FString& OutPrompt) const;

	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

	bool bSideView = false;
	float InvT = 0.f;
	float DashT = 0.f;

private:
	void HandleKeys(float Dt);
	float AttackT = 0.f;
	float ReachT = 0.f;
	FVector SpawnLocation = FVector::ZeroVector;
};
